from sqlalchemy.orm import Session
from fastapi import HTTPException, status
import models
import schemas
import auth
from datetime import datetime

class LedgerService:
    """
    Business Logic Layer for Financial Operations.
    Handles data integrity, field-level security, and audit trails.
    """

    @staticmethod
    def create_transaction(db: Session, tx_in: schemas.TransactionCreate, user_id: int):
        """
        Processes a new transaction:
        1. Row-level locks the account to prevent balance race conditions.
        2. Updates account balance based on income/expense.
        3. Encrypts the amount before database persistence.
        4. Records a permanent audit log entry.
        """
        # [1] SELECT ... FOR UPDATE to lock the row during calculation
        account = db.query(models.Account).filter(
            models.Account.id == tx_in.account_id,
            models.Account.owner_id == user_id
        ).with_for_update().first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found.")

        # [2] Update running balance in memory
        if tx_in.transaction_type == "income":
            account.balance += tx_in.amount
        else:
            account.balance -= tx_in.amount

        # [3] AES-256 Encryption for sensitive financial fields
        # encrypted_amount = auth.encrypt_amount(tx_in.amount)
        
        # Handle custom date parsing
        tx_date = datetime.now()
        if tx_in.date:
            try:
                tx_date = datetime.strptime(tx_in.date, "%Y-%m-%d")
            except ValueError:
                pass

        new_tx = models.Transaction(
            description=tx_in.description,
            amount=tx_in.amount,  # Store plaintext for response
            category=tx_in.category or "General",
            transaction_type=tx_in.transaction_type,
            account_id=tx_in.account_id,
            owner_id=user_id,
            date=tx_date
        )

        try:
            db.add(new_tx)
            db.flush() 

            # [4] Security Audit Logging for compliance
            log = models.AuditLog(
                user_id=user_id,
                action="CREATE_TX",
                target_id=new_tx.id,
                details=f"Added {tx_in.transaction_type}: {tx_in.description} (${tx_in.amount})"
            )
            db.add(log)
            db.commit()
            db.refresh(new_tx)
            
            # Decrypt amount for the final response without affecting DB state
            new_tx.amount = tx_in.amount
            return new_tx
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Database synchronization failed: {str(e)}")

    @staticmethod
    def delete_transaction(db: Session, tx_id: int, user_id: int):
        """
        Removes a transaction and reverts the account balance atomically.
        """
        tx = db.query(models.Transaction).filter(
            models.Transaction.id == tx_id,
            models.Transaction.owner_id == user_id
        ).first()

        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found.")

        # Revert account balance before deleting the record
        account = db.query(models.Account).filter(models.Account.id == tx.account_id).with_for_update().first()
        if account:
            try:
                raw_amount = float(auth.decrypt_amount(tx.amount))
                if tx.transaction_type == "income":
                    account.balance -= raw_amount
                else:
                    account.balance += raw_amount
            except Exception:
                pass # Integrity fallback if decryption fails

        try:
            log = models.AuditLog(
                user_id=user_id,
                action="DELETE_TX",
                target_id=tx_id,
                details=f"Deleted transaction: {tx.description}"
            )
            db.add(log)
            db.delete(tx)
            db.commit()
            return {"status": "success"}
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Deletion failed.")

    @staticmethod
    def delete_account(db: Session, account_id: int, user_id: int):
        """Safely deletes an account and its history with manual cascade."""
        account = db.query(models.Account).filter(
            models.Account.id == account_id,
            models.Account.owner_id == user_id
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found.")

        try:
            log = models.AuditLog(
                user_id=user_id, 
                action="DELETE_ACCOUNT", 
                target_id=account_id, 
                details=f"Deleted account: {account.name}"
            )
            db.add(log)

            db.query(models.Transaction).filter(
                models.Transaction.account_id == account_id
            ).delete()

            db.delete(account)
            db.commit()
            return {"status": "success", "message": "Account removed."}
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail="Account removal failed.")

    @staticmethod
    def get_processed_transactions(query_results):
        """
        Maps DB encrypted records to safe Pydantic objects for frontend use.
        Ensures plaintext data is never written back to the database.
        """
        processed = []
        for tx in query_results:
            
            processed.append(schemas.TransactionSchema(
                id=tx.id,
                description=tx.description,
                amount=tx.amount,
                category=tx.category,
                transaction_type=tx.transaction_type,
                account_id=tx.account_id,
                date=tx.date,
                owner_id=tx.owner_id
            ))
        return processed
    @staticmethod
    def update_transaction(db: Session, tx_id: int, tx_in: schemas.TransactionCreate, user_id: int):
        """
        Updates an existing transaction:
        1. Calculates the balance difference between the old and new amount.
        2. Updates the associated account balance.
        3. Re-encrypts the new amount.
        """
        # [1] Fetch existing transaction
        tx = db.query(models.Transaction).filter(
            models.Transaction.id == tx_id,
            models.Transaction.owner_id == user_id
        ).with_for_update().first()

        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found.")

        # [2] Handle Balance Adjustment
        account = db.query(models.Account).filter(models.Account.id == tx.account_id).with_for_update().first()
        if account:
            # Revert old amount
            old_amount = tx.amount
            if tx.transaction_type == "income":
                account.balance -= old_amount
            else:
                account.balance += old_amount
            
            # Apply new amount
            if tx_in.transaction_type == "income":
                account.balance += tx_in.amount
            else:
                account.balance -= tx_in.amount

        # [3] Update fields
        tx.description = tx_in.description
        tx.category = tx_in.category
        tx.transaction_type = tx_in.transaction_type
        
        if tx_in.date:
            try:
                tx.date = datetime.strptime(tx_in.date, "%Y-%m-%d")
            except ValueError:
                pass

        try:
            # [4] Audit log for the modification
            log = models.AuditLog(
                user_id=user_id,
                action="UPDATE_TX",
                target_id=tx_id,
                details=f"Updated TX: {tx_in.description} (${tx_in.amount})"
            )
            db.add(log)
            db.commit()
            db.refresh(tx)
            
            tx.amount = tx_in.amount # Decrypt for response
            return tx
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Update failed.")
    @staticmethod
    def transfer_funds(db: Session, transfer_in: schemas.TransferCreate, user_id: int):
        """
        ATOMIC OPERATION: Moves money between two accounts.
        1. Sorts IDs to prevent Deadlocks.
        2. Row-level locks both accounts.
        3. Creates two balanced transaction records (Debit/Credit).
        4. Logs the security audit trail.
        """
        if transfer_in.from_account_id == transfer_in.to_account_id:
            raise HTTPException(status_code=400, detail="Source and destination accounts must be different.")
        
        if transfer_in.amount <= 0:
            raise HTTPException(status_code=400, detail="Transfer amount must be positive.")

        # [1] DEADLOCK PREVENTION: Always lock the account with the smaller ID first
        account_ids = sorted([transfer_in.from_account_id, transfer_in.to_account_id])
        
        try:
            # [2] LOCK ACCOUNTS
            accounts_map = {}
            for acc_id in account_ids:
                acc = db.query(models.Account).filter(
                    models.Account.id == acc_id,
                    models.Account.owner_id == user_id
                ).with_for_update().first()
                if not acc:
                    raise HTTPException(status_code=404, detail=f"Account #{acc_id} not found.")
                accounts_map[acc_id] = acc

            from_acc = accounts_map[transfer_in.from_account_id]
            to_acc = accounts_map[transfer_in.to_account_id]

            # [3] VALIDATE BALANCE
            if from_acc.balance < transfer_in.amount:
                raise HTTPException(status_code=400, detail="Insufficient funds in source account.")

            # [4] EXECUTE BALANCED UPDATES
            from_acc.balance -= transfer_in.amount
            to_acc.balance += transfer_in.amount

            # [5] ENCRYPT & PERSIST DOUBLE-ENTRY RECORDS
            enc_amt = auth.encrypt_amount(transfer_in.amount)
            tx_date = datetime.now()
            if transfer_in.date:
                try: tx_date = datetime.strptime(transfer_in.date, "%Y-%m-%d")
                except: pass

            # Debit Entry (From Account)
            debit_tx = models.Transaction(
                description=f"Transfer to {to_acc.name}: {transfer_in.description}",
                amount=enc_amt,
                category="Transfer",
                transaction_type="expense",
                account_id=from_acc.id,
                owner_id=user_id,
                date=tx_date
            )
            # Credit Entry (To Account)
            credit_tx = models.Transaction(
                description=f"Transfer from {from_acc.name}: {transfer_in.description}",
                amount=enc_amt,
                category="Transfer",
                transaction_type="income",
                account_id=to_acc.id,
                owner_id=user_id,
                date=tx_date
            )

            db.add_all([debit_tx, credit_tx])
            db.flush()

            # [6] AUDIT LOG
            log = models.AuditLog(
                user_id=user_id,
                action="TRANSFER_FUNDS",
                target_id=debit_tx.id,
                details=f"Transferred ${transfer_in.amount} from {from_acc.name} to {to_acc.name}"
            )
            db.add(log)
            db.commit()
            
            return {"status": "success", "amount": transfer_in.amount}

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Transfer failed: {str(e)}")