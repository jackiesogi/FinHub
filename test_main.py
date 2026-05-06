import pytest
import time
import uuid
import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Local imports
from database import Base, get_db
from main import app
import models

# --- FIXED LOGGING SETUP: ENSURING PERSISTENT OUTPUT ---
# We use the root logger and set 'delay=False' to force file creation
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("test_evidence.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# --- TEST DB CONFIG ---
TEST_DB = "sqlite:///./test_fintech.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def init_db():
    log.info("--- TEST SESSION START: Initializing DB ---")
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    log.info("--- TEST SESSION END: Cleaning Up ---")
    # Force close handlers to flush the final logs to disk
    for handler in logging.root.handlers:
        handler.close()

def get_auth_client():
    uid = uuid.uuid4().hex[:6]
    user, pw = f"user_{uid}", "pass123"
    client.post("/api/v1/auth/register", json={"username": user, "email": f"{user}@test.com", "password": pw})
    login_res = client.post("/api/v1/auth/login", data={"username": user, "password": pw})
    token = login_res.json()['access_token']
    return user, {"Authorization": f"Bearer {token}"}

# --- 4 SCENARIOS WITH DIRECT SQL EVIDENCE ---

def test_scenario_1_standard_transfer():
    """Verify standard transfer by checking RAW DB values."""
    user, auth = get_auth_client()
    log.info(f"[SCENARIO 1] Standard Flow for {user}")

    a1 = client.post("/api/v1/accounts", headers=auth, json={"name": "Vault_A", "balance": 1000.0}).json()
    a2 = client.post("/api/v1/accounts", headers=auth, json={"name": "Vault_B", "balance": 50.0}).json()

    client.post("/api/v1/transfers", headers=auth, json={
        "from_account_id": a1['id'], "to_account_id": a2['id'], "amount": 200.0
    })

    # PROOF: SQL check directly from the engine
    with engine.connect() as conn:
        query = text("SELECT name, balance FROM accounts WHERE owner_id = (SELECT id FROM users WHERE username = :u)")
        rows = conn.execute(query, {"u": user}).fetchall()
        for name, balance in rows:
            log.info(f"   >>> DB EVIDENCE | Account: {name} | Raw_Balance: {balance}")
            if name == "Vault_A": assert balance == 800.0
            if name == "Vault_B": assert balance == 250.0
    log.info("✅ SCENARIO 1 PASSED.")

def test_scenario_2_overdraft_prevention():
    """Verify overdraft block and ensure balance REMAINS UNCHANGED in DB."""
    user, auth = get_auth_client()
    log.info(f"[SCENARIO 2] Overdraft Check for {user}")

    acc_src = client.post("/api/v1/accounts", headers=auth, json={"name": "SmallVault", "balance": 10.0}).json()
    acc_dst = client.post("/api/v1/accounts", headers=auth, json={"name": "TargetVault", "balance": 0.0}).json()

    log.info(f"   💸 Attempting illegal transfer: $99,999 from {acc_src['name']}")
    res = client.post("/api/v1/transfers", headers=auth, json={
        "from_account_id": acc_src['id'],
        "to_account_id": acc_dst['id'],
        "amount": 99999.0
    })

    assert res.status_code == 400

    # PROOF: Direct SQL check
    with engine.connect() as conn:
        db_val = conn.execute(text("SELECT balance FROM accounts WHERE id = :id"), {"id": acc_src['id']}).scalar()
        log.info(f"   >>> DB EVIDENCE | ID:{acc_src['id']} | Current_Balance: {db_val}")
        assert db_val == 10.0
    log.info("✅ SCENARIO 2 PASSED.")

def test_scenario_3_negative_amount():
    """Verify negative input rejection and ensure no DB state change."""
    user, auth = get_auth_client()
    log.info(f"[SCENARIO 3] Negative Amount Check for {user}")

    acc = client.post("/api/v1/accounts", headers=auth, json={"name": "FixedVault", "balance": 500.0}).json()

    res = client.post("/api/v1/transfers", headers=auth, json={
        "from_account_id": acc['id'], "to_account_id": 1, "amount": -100.0
    })
    assert res.status_code == 400

    # PROOF: Check DB hasn't moved
    with engine.connect() as conn:
        db_val = conn.execute(text("SELECT balance FROM accounts WHERE id = :id"), {"id": acc['id']}).scalar()
        log.info(f"   >>> DB EVIDENCE | ID:{acc['id']} | Balance: {db_val}")
        assert db_val == 500.0
    log.info("✅ SCENARIO 3 PASSED.")

def test_scenario_4_unauthorized_access():
    """Verify security guard (401)."""
    log.info("[SCENARIO 4] Unauthorized Access Guard")
    res = client.get("/api/v1/accounts")
    log.info(f"   >>> GUARD EVIDENCE | Response Status: {res.status_code}")
    assert res.status_code == 401
    log.info("✅ SCENARIO 4 PASSED.")
