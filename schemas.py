from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

# --- Identity & Access Management (IAM) Schemas ---

class UserCreate(BaseModel):
    """Schema for user registration."""
    username: str
    email: EmailStr
    password: str

class UserSchema(BaseModel):
    """Schema for user profile responses."""
    id: int
    username: str
    email: str

    class Config:
        from_attributes = True

class Token(BaseModel):
    """Schema for JWT authentication responses."""
    access_token: str
    token_type: str

# --- Account Management Schemas ---

class AccountBase(BaseModel):
    """Base definition for financial accounts."""
    name: str
    balance: float = 0.0
    account_type: str = "Checking" # e.g., Savings, Checking, Cash

class AccountCreate(AccountBase):
    """Schema for creating a new account."""
    pass

class AccountSchema(AccountBase):
    """Full account schema including database IDs."""
    id: int
    owner_id: int

    class Config:
        from_attributes = True

# --- Financial Transaction Schemas ---

class TransactionBase(BaseModel):
    """Base definition for a ledger entry."""
    description: str
    amount: float
    category: str
    transaction_type: str  # 'income' or 'expense'
    account_id: int        # [REQUIRED] Links the transaction to a specific account
    date: Optional[str] = None # Stores the custom date from the frontend

class TransactionCreate(TransactionBase):
    """Schema for creating a new transaction record."""
    account_id: int

class TransactionSchema(TransactionBase):
    """Full transaction record including timestamp and ownership."""
    id: int
    date: datetime
    owner_id: int

    class Config:
        from_attributes = True

# --- Analytics & Reporting Schemas ---

class DashboardSchema(BaseModel):
    """Schema for high-level financial KPIs."""
    total_income: float
    total_expense: float
    balance: float

class AuditLogSchema(BaseModel):
    """Schema for security and compliance log records."""
    id: int
    action: str
    target_id: int
    details: str
    timestamp: datetime

    class Config:
        from_attributes = True

class TransferCreate(BaseModel):
    """Schema for moving funds between two internal accounts."""
    from_account_id: int
    to_account_id: int
    amount: float
    description: Optional[str] = "Internal Transfer智匯轉帳"
    date: Optional[str] = None
