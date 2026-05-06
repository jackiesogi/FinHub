from database import engine
import models

def reset_database():
    print("⚠️  CRITICAL WARNING: This will PERMANENTLY DELETE all financial records!")
    confirm = input("Are you sure you want to WIPE the entire database? (y/n): ")

    if confirm.lower() == 'y':
        # [1] DROP ALL TABLES (SQLAlchemy handles foreign key order automatically)
        print("Force dropping all tables via SQLAlchemy metadata...")
        models.Base.metadata.drop_all(bind=engine)

        # [2] RECREATE TABLES
        print("Recreating tables from the latest models.py...")
        models.Base.metadata.create_all(bind=engine)

        print("\n✅ Database Reset Complete! System is now in a clean state.")
    else:
        print("Operation cancelled. Data is safe.")

if __name__ == "__main__":
    reset_database()
