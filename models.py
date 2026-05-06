from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from database import Base

class User(Base):
    """
    User Management: Stores identity and provides relations to financial data.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    # Relationships
    # Added cascade to User->Accounts so deleting a user wipes their data
    accounts = relationship("Account", back_populates="owner", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="owner", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user_ref")
    accounts = relationship("Account", back_populates="owner") # [ADD THIS LINE] Establishes a relationship to count accounts per user

class Account(Base):
    """
    Financial Accounts: Separate containers for funds (e.g., Cash, Bank, Savings).
    Tracks real-time balance for each account.
    """
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True) # Account Name: e.g., "Cash", "E.SUN Bank"
    balance = Column(Float, default=0.0)
    account_type = Column(String)    # e.g., "Checking", "Savings", "Credit Card"
    owner_id = Column(Integer, ForeignKey("users.id"))

    # Relationship to User
    owner = relationship("User", back_populates="accounts")

    # [CRITICAL UPDATE] Cascade Delete Logic:
    # 'cascade="all, delete-orphan"' ensures that when an Account is deleted,
    # all its child Transaction objects are also purged from the database.
    transactions = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan"
    )

class Transaction(Base):
    """
    Transaction Ledger: The core data model for income and expense records.
    Fields are encrypted at rest for financial security.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String)
    amount = Column(Float)  # Encrypted string
    category = Column(String)
    transaction_type = Column(String)
    date = Column(DateTime, default=func.now())
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"))
    owner_id = Column(Integer, ForeignKey("users.id"))

    # [DATABASE LEVEL CASCADE]
    # 'ondelete="CASCADE"' ensures referential integrity at the SQL engine level.
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"))

    # Relationships
    account = relationship("Account", back_populates="transactions")
    owner = relationship("User", back_populates="transactions")

class AuditLog(Base):
    """
    Audit Trail: Permanent log of sensitive operations (Create/Delete).
    Critical for financial compliance and accountability.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)      # e.g., "CREATE", "DELETE"
    target_id = Column(Integer)  # ID of the affected entity
    details = Column(String)     # Human-readable change summary
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationship back to User
    user_ref = relationship("User", back_populates="audit_logs")
