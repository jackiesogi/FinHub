import os

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from config import settings

# Absolute, so the DB does not follow the working directory the process
# happened to start in.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'finhub.db')}"

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL or DEFAULT_SQLITE_URL

# check_same_thread is a SQLite-only argument; passing it to Postgres fails.
_connect_args = ({"check_same_thread": False}
                 if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {})

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=_connect_args)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite ignores ON DELETE CASCADE unless foreign keys are switched on."""
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
