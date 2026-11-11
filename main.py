"""FinHub — the front end for the CJTrade trading engine.

Three things the UI needs and three sources for them, each the only one that
can answer its own questions:

    engine  (:8898, read-only)  what the bots are doing right now
    broker  (:8802)             the account, the orders, the market
    FinHub's own DB             that a run happened, and who placed what by hand

Every one of those calls is made here, server-side. The browser talks only to
FinHub — see cjtrade/__init__.py for why that is the whole design and not a
detail.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

import auth
import models
import schemas
from auth import get_current_user
from cjtrade import ArenaXClient
from cjtrade import BrokerError
from cjtrade import EngineClient
from cjtrade import EngineUnavailable
from cjtrade import RunConfig
from cjtrade import RunSupervisor
from cjtrade import SupervisorError
from config import settings
from database import engine as db_engine
from database import get_db

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("finhub")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

engine_client = EngineClient(settings.engine_base_url)
broker_client = ArenaXClient(settings.arenax_base_url, settings.ARENAX_API_KEY)
supervisor = RunSupervisor(repo=settings.CJTRADE_REPO, uv_bin=settings.UV_BIN,
                           log_dir=settings.RUN_LOG_DIR)


# ══════════════════════════════════════════════════════════════════════════════
#  Lifespan
# ══════════════════════════════════════════════════════════════════════════════

def _close_out_orphaned_runs() -> None:
    """Mark runs that were in flight when FinHub last stopped.

    The supervisor keeps its children in memory, so a FinHub that is killed --
    a reboot, a crash, a Ctrl-C in the wrong window -- comes back with no idea
    that run 10 ever existed. `_watch_run` then skips it forever, because it
    bails on `run_id is None`, and the row sits at "running" describing
    processes that died with the machine.

    Said as "interrupted" rather than "finished" or "failed": nothing is known
    about how it ended, and claiming either would be inventing a result.
    """
    from database import SessionLocal

    with SessionLocal() as db:
        stale = (db.query(models.Run)
                 .filter(models.Run.status.in_(("starting", "running")))
                 .all())
        for run in stale:
            run.status = "interrupted"
            run.ended_at = run.ended_at or datetime.utcnow()
            run.error = (run.error or
                         "FinHub stopped while this run was in flight, so how "
                         "it ended was never recorded. Its processes did not "
                         "survive.")
        if stale:
            db.commit()
            log.warning("marked %d run(s) as interrupted: %s", len(stale),
                        ", ".join(str(r.id) for r in stale))


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=db_engine)
    # Before the watcher starts, so it never sees a row it cannot explain.
    _close_out_orphaned_runs()
    log.info("engine status API : %s", settings.engine_base_url)
    log.info("arenax broker     : %s", settings.arenax_base_url)
    log.info("cjtrade checkout  : %s%s", settings.CJTRADE_REPO,
             "" if settings.CJTRADE_REPO.is_dir() else "  (NOT FOUND)")
    watcher = asyncio.create_task(_watch_run(), name="run_watcher")
    try:
        yield
    finally:
        watcher.cancel()
        # This is the lifetime tie the supervisor exists for: closing FinHub
        # closes the run it started, rather than leaving an engine trading into
        # a broker with nobody watching either.
        await supervisor.shutdown()


async def _watch_run() -> None:
    """Notice when the engine process ends and close out its Run row.

    Polling rather than waiting on the process: the row has to be updated from
    the engine's *last reported* state, and that has to be read before the
    status API goes away with the process. So this samples while it is alive
    and writes what it last saw once it is not.
    """
    from database import SessionLocal

    # The engine's own numbers, kept from the last successful poll. They have
    # to be remembered rather than fetched at the end, because the thing that
    # reports them is the process that just exited.
    last_status: dict = {}
    last_trips: dict = {}

    while True:
        try:
            await asyncio.sleep(2.0)
            run_id = supervisor.run_id
            # Nothing to watch, or the engine has not been spawned yet. The
            # second case is the whole reason this is not just `not busy`:
            # starting a run sets the run id and then waits for the broker, so
            # for up to a minute and a half there is a run with no engine, and
            # treating that as "the engine has exited" finalised runs before
            # they began.
            if run_id is None or not supervisor.engine_started:
                continue

            if supervisor.engine_alive:
                try:
                    status = await engine_client.status()
                except EngineUnavailable:
                    status = None       # status site already torn down
                if status:
                    last_status = status
                    with SessionLocal() as db:
                        run = db.get(models.Run, run_id)
                        if run is not None and run.status == "starting":
                            run.status = "running"
                            run.session_id = status.get("session_id")
                            db.commit()
                    try:
                        trips = await engine_client.roundtrips()
                        if trips and trips.get("available"):
                            last_trips = trips
                    except EngineUnavailable:
                        pass
                continue

            # The engine is gone. Write what it last said, then release the
            # broker it was driving.
            exit_code = supervisor.engine_exit()
            with SessionLocal() as db:
                run = db.get(models.Run, run_id)
                if run is not None and run.ended_at is None:
                    _finalise_run(run, last_status, last_trips, exit_code,
                                  supervisor.tail(400))
                    db.commit()
                    log.info("run %s %s (exit %s)", run_id, run.status, exit_code)
            last_status, last_trips = {}, {}
            # Stops the leftover broker. Deliberate: a server reused across two
            # runs hands the second one the first one's balance, because
            # AX_STATE_FILE is commented out in every .cjsys and fresh state is
            # per server process. Ending it here is what makes the next run
            # start from a clean account.
            await supervisor.stop()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("run watcher hiccup — continuing")


def _finalise_run(run: models.Run, status: dict, trips: dict,
                  exit_code: Optional[int], tail: str) -> None:
    """Copy the engine's last word onto the Run row.

    Done from remembered samples rather than a fresh read, because by now there
    is no engine to ask. A run whose engine never reported anything keeps
    nulls, which is the honest answer and is why the UI offers the log for
    those instead of a summary.
    """
    run.ended_at = datetime.utcnow()
    run.exit_code = exit_code

    # A run someone stopped on purpose keeps that status: "stopped" and
    # "failed" are different facts and the UI shows them differently.
    if run.status == "stopped":
        pass
    elif exit_code not in (0, None):
        run.status = "failed"
        # The last few lines are where the traceback is; the whole tail would
        # not fit in a column worth reading.
        run.error = "\n".join(tail.strip().splitlines()[-12:]) or None
    else:
        run.status = "finished"

    progress = status.get("progress") or {}
    equity = status.get("equity") or {}
    risk = status.get("risk") or {}
    run.bars_served = progress.get("bars_served")
    run.final_equity = equity.get("current")
    run.pnl = equity.get("pnl")
    run.halt_reason = risk.get("halt_reason")
    if run.session_id is None:
        run.session_id = status.get("session_id")

    run.fills = trips.get("fills")
    run.round_trips = trips.get("closed")
    run.win_rate = trips.get("win_rate_pct")


def _audit(db: Session, user: models.User, action: str, target: str = "",
           details: str = "") -> None:
    db.add(models.AuditLog(user_id=user.id, action=action, target=str(target),
                           details=details))


app = FastAPI(
    title="FinHub",
    description="Front end for the CJTrade trading engine: run control, "
                "bot monitoring, manual trading.",
    version="0.2.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")),
          name="static")


# ══════════════════════════════════════════════════════════════════════════════
#  Pages
# ══════════════════════════════════════════════════════════════════════════════

PAGES = ("dashboard", "runs", "bots", "positions", "orders", "market",
         "trade", "audit")


@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.get("/register", response_class=HTMLResponse, tags=["Frontend"])
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")


# ══════════════════════════════════════════════════════════════════════════════
#  Identity
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/auth/register", response_model=schemas.UserSchema,
          tags=["Auth"])
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(
        or_(models.User.username == user_in.username,
            models.User.email == user_in.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Identity already exists.")
    user = models.User(username=user_in.username, email=user_in.email,
                       hashed_password=auth.hash_password(user_in.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/v1/auth/login", tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password,
                                            user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return {"access_token": auth.create_access_token(data={"sub": user.username}),
            "token_type": "bearer"}


@app.get("/api/v1/auth/me", response_model=schemas.UserSchema, tags=["Auth"])
def whoami(current_user: models.User = Depends(get_current_user)):
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
#  Engine  — the live view of a run
#
#  Every route answers 200 with {"available": false} when there is no engine,
#  because "no run in flight" is the normal state of this system and a 502
#  would have the UI render an error for it.
# ══════════════════════════════════════════════════════════════════════════════

def _absent(reason: str = "no run in flight") -> dict:
    return {"available": False, "reason": reason}


@app.get("/api/v1/engine/status", tags=["Engine"])
async def engine_status(current_user: models.User = Depends(get_current_user)):
    try:
        status = await engine_client.status()
    except EngineUnavailable as exc:
        return _absent(str(exc))
    return {"available": True, "status": status,
            "supervisor": supervisor.describe()}


@app.get("/api/v1/engine/bots", tags=["Engine"])
async def engine_bots(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, "bots": await engine_client.bots()}
    except EngineUnavailable as exc:
        return _absent(str(exc))


@app.get("/api/v1/engine/bots/{bot_id}/history", tags=["Engine"])
async def engine_bot_history(bot_id: str, limit: int = 120,
                             current_user: models.User = Depends(get_current_user)):
    try:
        history = await engine_client.bot_history(bot_id, limit=limit)
    except EngineUnavailable as exc:
        return _absent(str(exc))
    if history is None:
        raise HTTPException(status_code=404, detail=f"no such bot: {bot_id}")
    return {"available": True, **history}


@app.get("/api/v1/engine/equity", tags=["Engine"])
async def engine_equity(limit: int = 1000,
                        current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await engine_client.equity(limit=limit))}
    except EngineUnavailable as exc:
        return _absent(str(exc))


@app.get("/api/v1/engine/roundtrips", tags=["Engine"])
async def engine_roundtrips(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await engine_client.roundtrips())}
    except EngineUnavailable as exc:
        return _absent(str(exc))


# ══════════════════════════════════════════════════════════════════════════════
#  Broker  — one route per shell command, see README for the mapping
# ══════════════════════════════════════════════════════════════════════════════

def _broker_call(coro):
    """Turn a BrokerError into a 502 with the broker's own words.

    502 and not 500: the fault is upstream, and saying so is the difference
    between "FinHub is broken" and "start the ArenaX server".
    """
    async def run():
        try:
            return await coro
        except BrokerError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return run()


@app.get("/api/v1/broker/health", tags=["Broker"])
async def broker_health(current_user: models.User = Depends(get_current_user)):
    try:
        return {"available": True, **(await broker_client.health())}
    except BrokerError as exc:
        return _absent(str(exc))


@app.get("/api/v1/broker/account", tags=["Broker"])
async def broker_account(current_user: models.User = Depends(get_current_user)):
    """balance + lspos + lsodr in one read."""
    return await _broker_call(broker_client.account())


@app.get("/api/v1/broker/orders", tags=["Broker"])
async def broker_orders(current_user: models.User = Depends(get_current_user)):
    """lsodr."""
    return {"orders": await _broker_call(broker_client.orders())}


@app.get("/api/v1/broker/fills", tags=["Broker"])
async def broker_fills(session_id: Optional[str] = None,
                       current_user: models.User = Depends(get_current_user)):
    """Fill history with the commission and tax the broker charged."""
    return await _broker_call(broker_client.fills(session_id=session_id))


@app.get("/api/v1/broker/snapshot", tags=["Broker"])
async def broker_snapshot(symbols: str,
                          current_user: models.User = Depends(get_current_user)):
    """ohlcv. `symbols` is comma separated, as the shell takes them."""
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not wanted:
        raise HTTPException(status_code=422, detail="no symbols given")
    if len(wanted) > 20:
        raise HTTPException(status_code=422, detail="at most 20 symbols")
    return {"snapshots": await _broker_call(broker_client.snapshots(wanted))}


@app.get("/api/v1/broker/kbars", tags=["Broker"])
async def broker_kbars(symbol: str, start: str, end: str, interval: str = "1m",
                       current_user: models.User = Depends(get_current_user)):
    """kbars / replay. Range is [start, end) — end is exclusive."""
    return {"symbol": symbol,
            "kbars": await _broker_call(
                broker_client.kbars(symbol.strip().upper(), start, end, interval))}


@app.get("/api/v1/broker/clock", tags=["Broker"])
async def broker_clock(current_user: models.User = Depends(get_current_user)):
    """date / info. Naive Asia/Taipei — do not convert it in the UI."""
    clock = await _broker_call(broker_client.clock())
    return {"clock": clock,
            "market_open": await _broker_call(broker_client.is_market_open())}


@app.post("/api/v1/broker/orders", response_model=schemas.ManualOrderSchema,
          tags=["Broker"])
async def place_manual_order(order_in: schemas.OrderCreate,
                             db: Session = Depends(get_db),
                             current_user: models.User = Depends(get_current_user)):
    """buy / sell, by hand.

    Read this before using it: a manual order goes straight to the broker, so
    the engine's RiskGate never sees it. The per-bot allocation, the orders-
    per-bar limit, the duplicate check and the kill switch do not apply. The
    broker still checks what a broker checks — price, quantity, trading limit,
    balance, inventory — and refuses with a reason, which comes back as a
    REJECTED status rather than an error.

    It is also invisible to the bots: their ledger mirrors are built from the
    engine's order reports, so a manual fill moves the real balance underneath
    a bot that does not know it happened. Hence the audit row and the `confirm`
    flag.
    """
    if not order_in.confirm:
        raise HTTPException(
            status_code=422,
            detail="A manual order bypasses the engine's risk gate. "
                   "Set confirm=true to acknowledge.")

    result = await _broker_call(broker_client.place_order(
        symbol=order_in.symbol.strip().upper(),
        action=order_in.action,
        quantity=order_in.quantity,
        price=order_in.price,
        odd_lot=order_in.odd_lot,
        # Tagged, so this order is identifiable in the broker's fill history
        # as not having come from a bot. The engine filters its own report by
        # session_id, so an untagged manual fill would be silently excluded
        # from the run report while still having moved the balance.
        opt_field={"source": "finhub-manual", "user": current_user.username},
    ))

    record = models.ManualOrder(
        owner_id=current_user.id,
        run_id=supervisor.run_id,
        order_id=result["order_id"],
        symbol=order_in.symbol.strip().upper(),
        action=order_in.action,
        quantity=order_in.quantity,
        price=order_in.price,
        order_lot="IntraDayOdd" if order_in.odd_lot else "Common",
        status=result["status"],
        message=result["message"],
    )
    db.add(record)
    _audit(db, current_user, "MANUAL_ORDER", result["order_id"],
           f"{order_in.action} {order_in.symbol} x{order_in.quantity} "
           f"@ {order_in.price} -> {result['status']}")
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/v1/broker/manual-orders",
         response_model=list[schemas.ManualOrderSchema], tags=["Broker"])
def list_manual_orders(limit: int = 50, db: Session = Depends(get_db),
                       current_user: models.User = Depends(get_current_user)):
    """Which orders a human placed. The broker cannot answer this."""
    return (db.query(models.ManualOrder)
            .filter(models.ManualOrder.owner_id == current_user.id)
            .order_by(models.ManualOrder.id.desc())
            .limit(max(1, min(limit, 500))).all())


@app.delete("/api/v1/broker/orders/{order_id}", tags=["Broker"])
async def cancel_order(order_id: str, db: Session = Depends(get_db),
                       current_user: models.User = Depends(get_current_user)):
    result = await _broker_call(broker_client.cancel_order(order_id))
    _audit(db, current_user, "CANCEL_ORDER", order_id, result["status"])
    db.commit()
    return result


@app.post("/api/v1/broker/orders/cancel-all", tags=["Broker"])
async def cancel_all_orders(db: Session = Depends(get_db),
                            current_user: models.User = Depends(get_current_user)):
    """The shell's `cancel`: every order the broker will still cancel.

    Including a bot's. A run in flight will find its resting order gone and
    report it as cancelled to the bot, which is handled — but it is the bot's
    plan you just changed, so the UI asks first.
    """
    results = await _broker_call(broker_client.cancel_all())
    cancelled = [r for r in results if not r.get("skipped")
                 and r.get("status") == "CANCELLED"]
    _audit(db, current_user, "CANCEL_ALL", "",
           f"{len(cancelled)} cancelled of {len(results)} order(s)")
    db.commit()
    return {"results": results, "cancelled": len(cancelled),
            "examined": len(results)}


# ══════════════════════════════════════════════════════════════════════════════
#  Runs
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/runs", response_model=list[schemas.RunSchema], tags=["Runs"])
def list_runs(limit: int = 50, db: Session = Depends(get_db),
              current_user: models.User = Depends(get_current_user)):
    return (db.query(models.Run)
            .filter(models.Run.owner_id == current_user.id)
            .order_by(models.Run.id.desc())
            .limit(max(1, min(limit, 200))).all())


@app.get("/api/v1/runs/{run_id}", response_model=schemas.RunSchema, tags=["Runs"])
def get_run(run_id: int, db: Session = Depends(get_db),
            current_user: models.User = Depends(get_current_user)):
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/api/v1/runs", response_model=schemas.RunSchema, status_code=201,
          tags=["Runs"])
async def start_run(run_in: schemas.RunCreate, db: Session = Depends(get_db),
                    current_user: models.User = Depends(get_current_user)):
    """Start a backtest: bring up the broker, then the engine.

    Authenticated, because this spawns processes on the host. It runs a fixed
    program with validated arguments and no shell, so the request cannot choose
    what to execute — only how the engine is configured. `RunConfig.parse`
    bounds every number, because `days` becomes a replay length and an absurd
    one would have the engine fetching bars for minutes before anything could
    interrupt it.
    """
    try:
        cfg = RunConfig.parse(run_in.model_dump(),
                              default_arenax_port=settings.ARENAX_PORT,
                              default_status_port=settings.ENGINE_STATUS_PORT)
    except SupervisorError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run = models.Run(
        owner_id=current_user.id, broker=cfg.broker, mode=cfg.mode,
        symbols=",".join(cfg.symbols), days=cfg.days, fund=cfg.fund,
        speed=cfg.speed, start_date=cfg.start_date,
        arenax_port=cfg.arenax_port, status_port=cfg.status_port,
        status="starting",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        info = await supervisor.start(cfg, run.id)
    except SupervisorError as exc:
        run.status = "failed"
        run.error = str(exc)
        run.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        raise HTTPException(status_code=409, detail=str(exc))

    run.log_path = info["log"]
    # One slot per symbol. The engine spawns a single hardcoded Bot_C today, so
    # this records the intent; when it takes more than one bot the UI already
    # knows which strategy each id was meant to be.
    db.add(models.BotSlot(run_id=run.id, bot_id="Bot_C", strategy="BB",
                          symbol=cfg.symbols[0]))
    _audit(db, current_user, "START_RUN", str(run.id),
           f"{cfg.mode} {','.join(cfg.symbols)} days={cfg.days} "
           f"fund={cfg.fund:g} start={cfg.start_date or 'server default'}")
    db.commit()
    db.refresh(run)
    return run


@app.delete("/api/v1/runs/{run_id}", tags=["Runs"])
async def stop_run(run_id: int, db: Session = Depends(get_db),
                   current_user: models.User = Depends(get_current_user)):
    """Stop a run: engine first, then the broker.

    The engine's resting orders are cancelled by its own teardown, which is
    why the broker has to still be there when it goes.
    """
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    if supervisor.run_id != run_id:
        raise HTTPException(status_code=409,
                            detail="That run is not the one in flight.")

    result = await supervisor.stop()
    run.status = "stopped"
    run.ended_at = datetime.utcnow()
    _audit(db, current_user, "STOP_RUN", str(run_id), str(result))
    db.commit()
    return result


@app.get("/api/v1/runs/{run_id}/log", response_class=PlainTextResponse,
         tags=["Runs"])
def run_log(run_id: int, lines: int = 300, db: Session = Depends(get_db),
            current_user: models.User = Depends(get_current_user)):
    """The run's captured stdout and stderr.

    This is the only place a failure that happened before the engine's status
    API came up is visible at all, which is exactly when you most want it.
    """
    run = db.get(models.Run, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not run.log_path:
        return "This run never got as far as writing a log."
    return (supervisor.tail(lines=max(1, min(lines, 5000)),
                            path=Path(run.log_path))
            or "(log is empty)")


@app.get("/api/v1/supervisor", tags=["Runs"])
def supervisor_state(current_user: models.User = Depends(get_current_user)):
    """What FinHub currently has running, and where CJTrade is."""
    return supervisor.describe()


# ══════════════════════════════════════════════════════════════════════════════
#  Audit
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/audit", response_model=list[schemas.AuditLogSchema],
         tags=["Audit"])
def audit_logs(limit: int = 100, db: Session = Depends(get_db),
               current_user: models.User = Depends(get_current_user)):
    return (db.query(models.AuditLog)
            .filter(models.AuditLog.user_id == current_user.id)
            .order_by(models.AuditLog.id.desc())
            .limit(max(1, min(limit, 500))).all())


# ══════════════════════════════════════════════════════════════════════════════
#  SPA fallback. Last, so it cannot shadow a real route.
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/{path_name:path}", response_class=HTMLResponse, tags=["Frontend"])
async def catch_all(path_name: str, request: Request):
    """Serve the shell for a known page so a refresh keeps you where you were.

    An allowlist rather than "anything that is not an API path": a typo should
    be a 404, not a blank dashboard that looks like a bug in the page.
    """
    page = (path_name.strip("/").split("/") or [""])[0]
    if not page or page in PAGES:
        return templates.TemplateResponse(request, "index.html")
    raise HTTPException(status_code=404,
                        detail=f"No page {page!r}. Try: {', '.join(PAGES)}")
