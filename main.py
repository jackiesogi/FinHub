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
    # TemplateResponse expects (request, name, context)
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

