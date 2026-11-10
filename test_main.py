"""Tests for FinHub.

Both upstreams are faked, so none of this needs a running engine or broker.
What that cannot cover is the contract itself — that the ArenaX server still
wants `order_lot: "IntraDayOdd"` and `type: "Stocks"`. Those live as named
constants in cjtrade/arenax_client.py and are asserted here so a careless edit
to them fails something.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-key-not-used-anywhere-real")

import main  # noqa: E402
from cjtrade import BrokerError  # noqa: E402
from cjtrade import EngineUnavailable  # noqa: E402
from cjtrade import RunConfig  # noqa: E402
from cjtrade import SupervisorError  # noqa: E402
from cjtrade import arenax_client  # noqa: E402
from database import Base  # noqa: E402
from database import get_db  # noqa: E402

# One in-memory DB shared by every connection in the test process; the default
# in-memory SQLite gives each connection its own blank database.
_engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def _override_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


main.app.dependency_overrides[get_db] = _override_db


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=_engine)
    # The lifespan would start the run watcher and create tables on the real
    # engine, so it is skipped: these tests are about routes, not the daemon.
    with TestClient(main.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture(scope="module")
def authed(client):
    name = f"tester_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/v1/auth/register", json={
        "username": name, "email": f"{name}@example.com",
        "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text
    res = client.post("/api/v1/auth/login",
                      data={"username": name, "password": "a-long-enough-password"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── auth is the gate on everything that touches money or processes ───────────

PROTECTED = [
    ("get", "/api/v1/engine/status"),
    ("get", "/api/v1/engine/bots"),
    ("get", "/api/v1/broker/account"),
    ("get", "/api/v1/broker/orders"),
    ("get", "/api/v1/runs"),
    ("get", "/api/v1/supervisor"),
    ("get", "/api/v1/audit"),
    ("post", "/api/v1/runs"),
    ("post", "/api/v1/broker/orders"),
    ("post", "/api/v1/broker/orders/cancel-all"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_sensitive_route_needs_a_token(client, method, path):
    """An unauthenticated POST /runs would spawn processes on the host, and an
    unauthenticated order route would trade."""
    res = (client.post(path, json={}) if method == "post"
           else client.get(path))
    assert res.status_code == 401, f"{method} {path} answered {res.status_code}"


def test_login_rejects_a_wrong_password(client, authed):
    res = client.post("/api/v1/auth/login",
                      data={"username": "nobody", "password": "wrong"})
    assert res.status_code == 401


# ── the engine being absent is normal, not an error ─────────────────────────

def test_engine_absent_is_a_200_not_a_502(client, authed, monkeypatch):
    """Most of the time there is no run. A 502 would have the UI render an
    error for the system's resting state."""
    async def boom(*a, **k):
        raise EngineUnavailable("connection refused")
    monkeypatch.setattr(main.engine_client, "status", boom)
    res = client.get("/api/v1/engine/status", headers=authed)
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_engine_status_is_passed_through_untouched(client, authed, monkeypatch):
    """Not re-modelled on purpose: a Pydantic mirror would drop any monitor
    field the strategy added until this file was edited too."""
    payload = {"session_id": "abc", "progress": {"bars_served": 7},
               "bots": {"Bot_C": {"monitors": {"something_new": 42}}}}

    async def ok(*a, **k):
        return payload
    monkeypatch.setattr(main.engine_client, "status", ok)
    body = client.get("/api/v1/engine/status", headers=authed).json()
    assert body["available"] is True
    assert body["status"]["bots"]["Bot_C"]["monitors"]["something_new"] == 42


def test_broker_unreachable_is_a_502_with_the_reason(client, authed, monkeypatch):
    async def boom(*a, **k):
        raise BrokerError("broker unreachable at http://127.0.0.1:8802")
    monkeypatch.setattr(main.broker_client, "account", boom)
    res = client.get("/api/v1/broker/account", headers=authed)
    assert res.status_code == 502
    assert "unreachable" in res.json()["detail"]


# ── the order payload must match what the broker parses ─────────────────────

def test_order_payload_matches_the_broker_contract():
    client_obj = arenax_client.ArenaXClient("http://127.0.0.1:1", "k")
    payload = client_obj.build_order("2317", "BUY", 80, 252.5, odd_lot=True)

    # The server requires all of these and 400s without them.
    for key in ("product", "action", "price", "quantity", "price_type",
                "order_type", "order_lot", "created_at", "id"):
        assert key in payload, key

    # ProductType.STOCK's *value* is "Stocks". Sending "STOCK" gets rejected.
    assert payload["product"]["type"] == "Stocks"
    assert payload["product"]["exchange"] == "TSE"
    # The only shape this broker path sends, matching ArenaXBrokerAPI_v2.
    assert payload["price_type"] == "LMT"
    assert payload["order_type"] == "ROD"
    assert payload["order_lot"] == "IntraDayOdd"
    assert len(payload["id"]) == 32          # uuid4 hex, the caller's own id


def test_common_lot_is_the_other_order_lot():
    client_obj = arenax_client.ArenaXClient("http://127.0.0.1:1", "k")
    payload = client_obj.build_order("2317", "SELL", 1000, 250.0, odd_lot=False)
    assert payload["order_lot"] == "Common"
    assert payload["action"] == "SELL"


def test_cancellable_statuses_match_the_shell():
    """The shell's `cancel` skips anything outside this set; a UI that tried to
    cancel a FILLED order would just collect errors."""
    assert "COMMITTED_WAIT_MATCHING" in arenax_client.CANCELLABLE
    assert "PARTIAL" in arenax_client.CANCELLABLE
    for resolved in ("FILLED", "CANCELLED", "REJECTED", "UNKNOWN"):
        assert resolved not in arenax_client.CANCELLABLE


# ── a manual order is acknowledged, recorded and tagged ─────────────────────

def test_a_manual_order_without_confirmation_is_refused(client, authed):
    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 10, "price": 100.0,
        "odd_lot": True, "confirm": False})
    assert res.status_code == 422
    assert "risk gate" in res.json()["detail"]


def test_a_manual_order_is_tagged_and_recorded(client, authed, monkeypatch):
    """Tagged because the engine filters its run report by session_id, so an
    untagged manual fill would be excluded from the report while still having
    moved the balance."""
    seen = {}

    async def fake_place(**kwargs):
        seen.update(kwargs)
        return {"order_id": "deadbeef" * 4, "status": "FILLED",
                "message": "Order filled.", "metadata": {}, "request": {}}
    monkeypatch.setattr(main.broker_client, "place_order", fake_place)

    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 80, "price": 252.5,
        "odd_lot": True, "confirm": True})
    assert res.status_code == 200, res.text
    assert seen["opt_field"]["source"] == "finhub-manual"
    assert "user" in seen["opt_field"]

    listed = client.get("/api/v1/broker/manual-orders", headers=authed).json()
    assert listed[0]["symbol"] == "2317"
    assert listed[0]["status"] == "FILLED"
    assert listed[0]["order_lot"] == "IntraDayOdd"

    audit = client.get("/api/v1/audit", headers=authed).json()
    assert any(row["action"] == "MANUAL_ORDER" for row in audit)


def test_a_broker_rejection_is_reported_not_raised(client, authed, monkeypatch):
    """The broker answering "no" is a verdict, and the reason is the useful
    part. A 500 here would hide it."""
    async def rejected(**kwargs):
        return {"order_id": "a" * 32, "status": "REJECTED",
                "message": "Insufficient balance", "metadata": {}, "request": {}}
    monkeypatch.setattr(main.broker_client, "place_order", rejected)
    res = client.post("/api/v1/broker/orders", headers=authed, json={
        "symbol": "2317", "action": "BUY", "quantity": 999999, "price": 252.5,
        "odd_lot": True, "confirm": True})
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"
    assert res.json()["message"] == "Insufficient balance"


# ── RunConfig is where a run request is made safe ───────────────────────────

def _parse(**raw):
    return RunConfig.parse(raw, default_arenax_port=8802,
                           default_status_port=8898)


def test_run_config_accepts_a_sensible_request():
    cfg = _parse(symbols=["2317", "0050"], mode="backtest", days=20,
                 fund=1_000_000, speed=1, start_date="2026-09-01")
    assert cfg.symbols == ["2317", "0050"]
    assert cfg.arenax_port == 8802 and cfg.status_port == 8898


def test_run_config_takes_a_comma_string_too():
    assert _parse(symbols="2317, 2330 ").symbols == ["2317", "2330"]


@pytest.mark.parametrize("symbols", [
    [], ["../../etc/passwd"], ["2317; rm -rf /"], ["$(whoami)"], ["ab"],
    ["2317 2330"],
])
def test_run_config_refuses_anything_that_is_not_a_symbol(symbols):
    """No shell is involved in spawning, so this is not about shell injection.
    It is about not handing the engine something that cannot be a ticker and
    then debugging the result."""
    with pytest.raises(SupervisorError):
        _parse(symbols=symbols)


@pytest.mark.parametrize("kwargs", [
    {"days": 0}, {"days": 20000}, {"days": -5},
    {"fund": 1}, {"fund": 10 ** 12},
    {"speed": -1},
    {"mode": "real"}, {"mode": "nonsense"},
    {"start_date": "yesterday"},
])
def test_run_config_bounds_every_number(kwargs):
    """`days` becomes a replay length: an absurd one has the engine fetching
    bars for minutes before anything can interrupt it."""
    with pytest.raises(SupervisorError):
        _parse(symbols=["2317"], **kwargs)



def test_speed_zero_means_flat_out_and_is_allowed():
    """0 is how you ask for an unpaced replay. The engine honours the speed in
    backtest now, so without this there would be no way to ask for the
    behaviour every backtest had before the setting meant anything."""
    assert _parse(symbols=["2317"], speed=0).speed == 0


def test_a_paced_speed_survives_parsing():
    assert _parse(symbols=["2317"], speed=1200).speed == 1200.0


def test_run_config_allows_an_empty_start_date():
    """Empty means "take the server's own timeline origin" to the engine, which
    is different from any date FinHub could invent."""
    assert _parse(symbols=["2317"], start_date="").start_date == ""


def test_run_config_refuses_real_mode():
    """"real" is a CJTrade backend that trades an actual account. It is not on
    the list a web form can pick from."""
    with pytest.raises(SupervisorError):
        _parse(symbols=["2317"], mode="real")


# ── supervisor state ────────────────────────────────────────────────────────

def test_supervisor_starts_idle(client, authed):
    body = client.get("/api/v1/supervisor", headers=authed).json()
    assert body["busy"] is False
    assert body["run_id"] is None
    assert body["children"] == []


def test_a_broker_that_outlives_the_engine_is_not_a_run_in_flight():
    """`busy` used to mean "any child alive". The broker outlives the engine
    during teardown, so a finished run looked like it was still going: its row
    never got a summary and the next run was refused as a conflict."""
    import subprocess

    from cjtrade import supervisor as sup_mod

    sup = main.supervisor
    sup._children = []
    fake_broker = sup_mod.Child(name="broker", argv=[],
                                popen=subprocess.Popen(["sleep", "30"]),
                                log_path=main.settings.RUN_LOG_DIR / "x.log")
    dead_engine = sup_mod.Child(name="engine", argv=[],
                                popen=subprocess.Popen(["true"]),
                                log_path=main.settings.RUN_LOG_DIR / "x.log")
    dead_engine.popen.wait()
    sup._children = [fake_broker, dead_engine]
    try:
        assert sup.broker_alive is True
        assert sup.engine_started is True
        assert sup.engine_alive is False
        assert sup.busy is False          # the run is over
        assert sup.engine_exit() == 0     # readable after the process is gone
    finally:
        fake_broker.popen.kill()
        sup._children = []


def test_a_run_whose_engine_has_not_spawned_yet_is_not_finished():
    """Starting a run sets the run id, then waits for the broker. Treating that
    window as "the engine has exited" finalised runs before they began."""
    import subprocess

    from cjtrade import supervisor as sup_mod

    sup = main.supervisor
    sup._children = []
    broker = sup_mod.Child(name="broker", argv=[],
                           popen=subprocess.Popen(["sleep", "30"]),
                           log_path=main.settings.RUN_LOG_DIR / "x.log")
    sup._children = [broker]
    try:
        assert sup.engine_started is False
        assert sup.engine_alive is False
        assert sup.engine_exit() is None
    finally:
        broker.popen.kill()
        sup._children = []


def test_starting_a_run_without_a_checkout_fails_cleanly(client, authed,
                                                          monkeypatch, tmp_path):
    """A missing CJTrade checkout should be a 409 that names the path, not a
    traceback and a half-started run."""
    monkeypatch.setattr(main.supervisor, "repo", tmp_path / "not-here")
    res = client.post("/api/v1/runs", headers=authed,
                      json={"symbols": ["2317"], "mode": "backtest", "days": 5})
    assert res.status_code == 409
    assert "not found" in res.json()["detail"]

    # The Run row still exists, marked failed, with the reason on it: a run
    # that never started is still something you want to see in the list.
    runs = client.get("/api/v1/runs", headers=authed).json()
    assert runs[0]["status"] == "failed"
    assert "not-here" in runs[0]["error"]


def test_a_run_log_for_a_run_that_never_started(client, authed):
    runs = client.get("/api/v1/runs", headers=authed).json()
    res = client.get(f"/api/v1/runs/{runs[0]['id']}/log", headers=authed)
    assert res.status_code == 200
    assert "never got as far" in res.text


def test_another_users_run_is_a_404(client, authed):
    res = client.get("/api/v1/runs/999999", headers=authed)
    assert res.status_code == 404


# ── pages ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/dashboard", "/runs", "/bots",
                                  "/positions", "/orders", "/market",
                                  "/trade", "/audit"])
def test_known_pages_serve_the_shell(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert "CJTrade Console" in res.text


def test_an_unknown_page_is_a_404_not_a_blank_dashboard(client):
    """A typo that silently rendered the dashboard looks like a bug in the
    page rather than a bad URL."""
    res = client.get("/not-a-page")
    assert res.status_code == 404
