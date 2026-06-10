# from fastapi import FastAPI

# app = FastAPI(title="OpenDataHub - Mini Depositar")

# @app.get("/")
# def read_root():
#     return {"message": "Hello from OpenDataHub! 🚀 這是我的研究資料平台 demo"}

# @app.get("/docs")
# def docs():
#     return {"redirect": "去 http://127.0.0.1:8000/docs 看自動 API 文件"}

# @app.get("/hello/{name}")
# def say_hello(name: str):
#     return {"message": f"嗨，{name}！歡迎來到 OpenDataHub 🎉"}

from fastapi import FastAPI, Depends, Request, HTTPException, status, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pathlib import Path
from typing import Optional, List
from fastapi.staticfiles import StaticFiles

# Internal Module Imports
from database import get_db, engine
import models
import schemas
import auth
from auth import get_current_user
from services import LedgerService
from contextlib import asynccontextmanager
from config import settings



# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- Lifespan Management ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    Replaces the deprecated @app.on_event("startup") pattern.
    """
    # [Startup]: Logic to execute when the server starts
    # Create database tables if they do not exist
    models.Base.metadata.create_all(bind=engine)

    yield  # Control is handed over to the FastAPI application

    # [Shutdown]: Logic to execute when the server stops
    # (e.g., closing database connection pools or clearing cache)
    pass

# --- FastAPI Initialization ---

app = FastAPI(
    title="FinTechHub Secure",
    description="Enterprise Ledger with Field-Level Encryption.",
    version="2.2.0",
    lifespan=lifespan
)

# --- Static Files Configuration ---

# Mount the static directory to serve CSS, JS, and images
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Frontend Shell (SSR) ---

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def home(request: Request):
    # ✅ 新的響應式設計
    return templates.TemplateResponse(request, "index_responsive.html")

@app.get("/classic", response_class=HTMLResponse, tags=["Frontend"])
async def home_classic(request: Request):
    # 舊版設計（備用）
    return templates.TemplateResponse(request, "index.html")

@app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.get("/register", response_class=HTMLResponse, tags=["Frontend"])
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")

# --- IAM API ---

@app.post("/api/v1/auth/register", response_model=schemas.UserSchema, tags=["Auth"])
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    """Handles secure user registration."""
    db_user = db.query(models.User).filter(
        or_(models.User.username == user_in.username, models.User.email == user_in.email)
    ).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Identity already exists.")

    new_user = models.User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=auth.hash_password(user_in.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/api/v1/auth/login", tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Authenticates credentials and issues JWT token."""
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

# --- Finance API ---

@app.get("/api/v1/dashboard", tags=["Finance"])
def get_dashboard_summary(
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Calculates financial KPIs by decrypting and aggregating transactions."""
    tx_query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)

    if account_id:
        tx_query = tx_query.filter(models.Transaction.account_id == account_id)
        account = db.query(models.Account).filter(models.Account.id == account_id).first()
        total_balance = account.balance if account else 0
    else:
        total_balance = db.query(func.sum(models.Account.balance)).filter(
            models.Account.owner_id == current_user.id
        ).scalar() or 0

    txs = tx_query.all()
    # Decrypt records in-memory via Service Layer
    processed_txs = LedgerService.get_processed_transactions(txs)

    income = sum(t.amount for t in processed_txs if t.transaction_type == "income")
    expense = sum(t.amount for t in processed_txs if t.transaction_type == "expense")

    return {"total_income": income, "total_expense": expense, "balance": total_balance}

@app.get("/api/v1/accounts", response_model=List[schemas.AccountSchema], tags=["Finance"])
def list_accounts(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return db.query(models.Account).filter(models.Account.owner_id == current_user.id).all()

@app.post("/api/v1/accounts", status_code=201, tags=["Finance"])
def create_account(account_in: schemas.AccountCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    new_acc = models.Account(**account_in.dict(), owner_id=current_user.id)
    db.add(new_acc)
    db.commit()
    db.refresh(new_acc)
    return new_acc

@app.delete("/api/v1/accounts/{account_id}", tags=["Finance"])
def delete_account(account_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return LedgerService.delete_account(db, account_id, current_user.id)

@app.get("/api/v1/transactions", response_model=List[schemas.TransactionSchema], tags=["Finance"])
def list_transactions(
    account_id: Optional[int] = None,
    sort_by: Optional[str] = "date_desc",
    skip: int = 0,    # Offset for pagination
    limit: int = 20,  # Max records per request to prevent OOM (Out of Memory)
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Fetches paginated transactions with server-side filtering."""
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    if account_id:
        query = query.filter(models.Transaction.account_id == account_id)

    # Apply limit and offset at the database level before fetching to memory
    db_txs = query.offset(skip).limit(limit).all()
    processed_txs = LedgerService.get_processed_transactions(db_txs)

    # In-memory sorting remains necessary due to field-level encryption (ciphertexts cannot be sorted via SQL)
    sort_map = {
        "date_asc": (lambda x: x.date, False),
        "date_desc": (lambda x: x.date, True),
        "amount_asc": (lambda x: x.amount, False),
        "amount_desc": (lambda x: x.amount, True),
    }

    if sort_by in sort_map:
        key_func, is_reverse = sort_map[sort_by]
        processed_txs.sort(key=key_func, reverse=is_reverse)

    return processed_txs

@app.post("/api/v1/transactions", status_code=201, tags=["Finance"])
def create_transaction(tx_in: schemas.TransactionCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return LedgerService.create_transaction(db, tx_in, current_user.id)

@app.delete("/api/v1/transactions/{tx_id}", tags=["Finance"])
def delete_transaction(tx_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return LedgerService.delete_transaction(db, tx_id, current_user.id)

@app.get("/api/v1/audit-logs", tags=["Security"])
def get_audit_logs(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return db.query(models.AuditLog).filter(models.AuditLog.user_id == current_user.id).order_by(models.AuditLog.timestamp.desc()).all()

@app.put("/api/v1/transactions/{tx_id}", tags=["Finance"])
def update_transaction(
    tx_id: int,
    tx_in: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Updates a transaction's details and synchronizes the account balance."""
    return LedgerService.update_transaction(db, tx_id, tx_in, current_user.id)

@app.post("/api/v1/transfers", tags=["Finance"], status_code=201)
def internal_transfer(
    transfer_in: schemas.TransferCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Executes a secure internal transfer between two accounts owned by the user.
    Ensures ACID compliance and encrypted audit trailing.
    """
    return LedgerService.transfer_funds(db, transfer_in, current_user.id)

@app.get("/api/v1/admin/users", tags=["Admin"])
def get_system_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Administrative endpoint to monitor system growth.
    Restricted to specific admin username for security.
    """
    # [SECURITY CHECK] Replace 'Eason' with your actual admin username
    if current_user.username != "Eason":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required."
        )

    users = db.query(models.User).all()

    # [DATA AGGREGATION] Map user data and count their linked accounts
    admin_data = []
    for u in users:
        admin_data.append({
            "username": u.username,
            "email": u.email,
            "account_count": len(u.accounts)
        })

    return admin_data


@app.delete("/api/v1/accounts/{account_id}/transactions", tags=["Finance"])
def clear_account_transactions(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    清空特定帳戶的所有交易記錄，但保留帳戶本身。
    帳戶餘額會重設為 0。
    """
    # 驗證帳戶所有權
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.owner_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission."
        )

    try:
        # 刪除該帳戶的所有交易
        db.query(models.Transaction).filter(
            models.Transaction.account_id == account_id
        ).delete()

        # 重設帳戶餘額
        account.balance = 0.0
        db.commit()

        return {
            "status": "success",
            "message": f"Account '{account.name}' transactions cleared. Balance reset to 0.",
            "account_id": account_id,
            "account_name": account.name,
            "new_balance": 0.0
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear transactions: {str(e)}"
        )


@app.post("/api/v1/cjtrade/sync/{account_id}", tags=["CJTrade"])
def cjtrade_sync_account(
    account_id: int,
    cjtrade_url: str = "http://localhost:8899",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Reset an account's transactions and re-import from CJTrade.

    Steps:
    1. Verify account ownership.
    2. Clear all existing transactions + reset balance to 0.
    3. Fetch ``initial_equity`` and ``trades`` from CJTrade.
    4. Bulk-insert: one INITIAL income entry + one entry per trade (BUY=expense, SELL=income).
    5. Write an audit log entry.
    """
    import json as _json
    import urllib.request as _urllib_req

    # ── 1. ownership check ────────────────────────────────────────────────────
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.owner_id == current_user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    # ── 2. fetch from CJTrade ─────────────────────────────────────────────────
    def _get(path: str):
        req = _urllib_req.Request(
            f"{cjtrade_url}{path}",
            headers={"Authorization": "Bearer cjtrade-finhub-backend"},
        )
        with _urllib_req.urlopen(req, timeout=5) as resp:  # noqa: S310
            return _json.loads(resp.read())

    try:
        acct_data   = _get("/api/v1/account")
        trades_data = _get("/api/v1/trades")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"CJTrade unreachable: {exc}")

    # ── 3. clear existing transactions ────────────────────────────────────────
    db.query(models.Transaction).filter(
        models.Transaction.account_id == account_id,
    ).delete(synchronize_session=False)
    account.balance = 0.0

    # ── 4. build entry list ───────────────────────────────────────────────────
    from datetime import datetime as _dt

    cash_balance = acct_data.get("balance", 0.0)
    launch_mode  = acct_data.get("launch_mode", "unknown")
    session_id   = acct_data.get("session_id", "")

    entries = [{
        "description":       f"CJTrade 初始現金 [{launch_mode}]",
        "amount":            cash_balance,
        "category":          "Trading",
        "transaction_type":  "income",
        "date":              _dt.now(),
    }]

    # trades arrive newest-first; reverse so balance progresses chronologically
    for trade in reversed(trades_data):
        action = trade.get("action", "")
        symbol = trade.get("symbol", "")
        qty    = trade.get("quantity", 0)
        price  = trade.get("price", 0.0)
        amount = round(price * qty, 2)
        try:
            ts = _dt.fromisoformat(trade.get("timestamp", ""))
        except Exception:
            ts = _dt.now()

        if action == "BUY":
            tx_type = "expense"
            desc    = f"買入 {symbol} ×{qty} @{price}"
        else:
            tx_type = "income"
            desc    = f"賣出 {symbol} ×{qty} @{price}"

        entries.append({
            "description":      desc,
            "amount":           amount,
            "category":         "Trading",
            "transaction_type": tx_type,
            "date":             ts,
        })

    # ── 5. bulk insert ────────────────────────────────────────────────────────
    for e in entries:
        db.add(models.Transaction(
            description=e["description"],
            amount=e["amount"],
            category=e["category"],
            transaction_type=e["transaction_type"],
            account_id=account_id,
            owner_id=current_user.id,
            date=e["date"],
        ))
        if e["transaction_type"] == "income":
            account.balance += e["amount"]
        else:
            account.balance -= e["amount"]

    db.add(models.AuditLog(
        user_id=current_user.id,
        action="CJTRADE_SYNC",
        target_id=account_id,
        details=(
            f"Reset & imported {len(entries)} entries from CJTrade "
            f"[{launch_mode}] session={session_id}"
        ),
    ))

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    return {
        "status":       "success",
        "imported":     len(entries),
        "launch_mode":  launch_mode,
        "session_id":   session_id,
        "new_balance":  round(account.balance, 2),
    }


@app.post("/api/v1/admin/reset-db")
def reset_database_endpoint(
    db: Session = Depends(get_db),
    # current_user: models.User = Depends(get_current_user)
):
    """
    Administrative endpoint to reset the entire database.
    Clears all tables and recreates the schema.
    Restricted to admin username for security.
    No confirmation required - use with caution!
    """
    # [SECURITY CHECK] Only admin can reset database
    # if current_user.username != "Eason":
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Administrative privileges required."
    #     )

    try:
        # Close the current session to release any locks
        db.close()

        # Drop all tables
        models.Base.metadata.drop_all(bind=engine)

        # Recreate all tables
        models.Base.metadata.create_all(bind=engine)

        return {
            "status": "success",
            "message": "Database reset complete! All tables have been cleared and recreated.",
            "timestamp": str(models.Base.metadata.tables)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {str(e)}"
        )


# --- Catch-All Route for SPA Routing ---
# Must be placed after all specific routes!

@app.get("/{path_name:path}", response_class=HTMLResponse, tags=["Frontend"])
async def catch_all(path_name: str, request: Request):
    """
    Catch-all route for Single Page Application (SPA) routing.

    Allows the frontend to handle URL routing while serving the same HTML shell.
    This enables URL persistence for pages like /dashboard, /assets, /audit
    without full page reloads.

    ✅ Benefits:
    - URL reflects current page state
    - Page refresh maintains current section
    - Supports sharing URLs
    - Browser back/forward buttons work
    - No duplicate HTML files needed

    Flow:
    1. User accesses /dashboard → Returns index_responsive.html
    2. Frontend's getPageFromURL() reads /dashboard
    3. showSection('dashboard') is called
    4. Dashboard page is displayed
    """

    # List of valid pages that should be served by SPA
    valid_pages = {
        "dashboard",      # Main financial dashboard
        "assets",         # Portfolio/holdings overview
        "audit",          # Security audit trail
        "settings",       # (Future) User settings
        "profile",        # (Future) User profile
    }

    # Extract the first path segment
    # e.g., /dashboard/detail → dashboard
    path_segments = path_name.strip("/").split("/") if path_name else []
    page = path_segments[0] if path_segments and path_segments[0] else ""

    # 🔍 Validation: Check if it's a valid SPA page
    if page in valid_pages or not page:
        # ✅ Valid page - serve the SPA shell
        # The frontend will read the URL and display the correct section
        return templates.TemplateResponse(request, "index_responsive.html")

    # ❌ Invalid page - return 404
    raise HTTPException(
        status_code=404,
        detail=f"Page '{page}' not found. Valid pages: {', '.join(valid_pages)}"
    )
