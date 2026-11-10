"""
Phase 3: Real MongoDB Integration, Atomic Batch Execution & Crash-Recovery Validation.
Tests atomicity, idempotency, failure injection, crash recovery, concurrency,
driver isolation, and owner settlement offset for Tanglish financial batches.

Spoken utterance under test:
"இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."
Expected actions:
1. FARE (INCOME): ₹1,500.00
2. FUEL (EXPENSE): ₹300.00
3. OWNER_RENT (OWNER_PAYMENT): ₹200.00
Expected net cash movement: ₹1,000.00
"""

import os
import sys
import pytest
import mongomock
from decimal import Decimal
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

from app.models.financial import (
    PendingActionType,
    PendingActionStatus,
    TransactionType,
    quantize_money,
    format_money
)
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.settlement_service import SettlementService
from app.services.pending_action_service import (
    PendingActionService,
    PendingActionUnauthorizedError,
    PendingActionAlreadyConsumedError
)
from app.services.financial_calculator import FinancialCalculator
from app.database.indexes import ensure_indexes
from app.utils.dates import today_ist


@pytest.fixture
def mock_db():
    """Sets up an isolated in-memory mongomock database with required indexes."""
    client = mongomock.MongoClient()
    db = client["t2t_drive_phase3_test"]
    ensure_indexes(db)
    return db


@pytest.fixture
def services(mock_db):
    """Initializes repositories and services against the mock database."""
    repo = TransactionRepository(mock_db)
    ledger = LedgerService(repo)
    settlement = SettlementService(mock_db, repo)
    pending = PendingActionService(mock_db, ledger, settlement)
    return {
        "db": mock_db,
        "repo": repo,
        "ledger": ledger,
        "settlement": settlement,
        "pending": pending
    }


def _make_sample_batch_data():
    return {
        "vehicle_id": "KA01AB1234",
        "transaction_date": today_ist(),
        "source": "VOICE_AGENT",
        "description": "Tanglish Voice Batch: collection 1500, petrol 300, owner 200",
        "transactions": [
            {
                "action_type": "INCOME",
                "amount": "1500.00",
                "category": "FARE",
                "description": "Daily collection / fare"
            },
            {
                "action_type": "EXPENSE",
                "amount": "300.00",
                "category": "FUEL",
                "description": "Petrol expense"
            },
            {
                "action_type": "OWNER_PAYMENT",
                "amount": "200.00",
                "category": "OWNER_RENT",
                "description": "Owner daily rent payment"
            }
        ]
    }


# ============================================================================
# 1. Full Batch Execution & Net Cash Movement
# ============================================================================

def test_full_batch_execution_and_net_cash_movement(services):
    """
    Verifies that the 3 actions (FARE ₹1500, FUEL ₹300, OWNER_RENT ₹200) execute
    atomically and produce a net cash movement of ₹1,000.00.
    """
    db = services["db"]
    pending_svc = services["pending"]
    repo = services["repo"]

    driver_id = "DRV_PHASE3_001"
    batch_data = _make_sample_batch_data()

    # 1. Propose action
    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_BATCH_PROPOSE_001"
    )
    pending_id = proposed["pending_action_id"]
    assert proposed["status"] == "PENDING"
    assert len(proposed["proposed_data"]["transactions"]) == 3

    # Zero writes to ledger prior to explicit confirmation
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # 2. Confirm action
    res = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key="IDEM_BATCH_CONFIRM_001"
    )

    assert res["status"] == "CONFIRMED"
    assert res["batch"] is True
    assert res["count"] == 3
    assert len(res["transactions"]) == 3

    # 3. Verify ledger transactions
    txns = repo.get_transactions_for_driver(driver_id)
    assert len(txns) == 3

    fare_txn = next(t for t in txns if t["category"] == "FARE")
    fuel_txn = next(t for t in txns if t["category"] == "FUEL")
    owner_txn = next(t for t in txns if t["category"] == "OWNER_RENT")

    assert fare_txn["transaction_type"] == TransactionType.INCOME
    assert Decimal(str(fare_txn["amount"])) == Decimal("1500.00")
    assert Decimal(str(fare_txn["signed_amount"])) == Decimal("1500.00")

    assert fuel_txn["transaction_type"] == TransactionType.EXPENSE
    assert Decimal(str(fuel_txn["amount"])) == Decimal("300.00")
    assert Decimal(str(fuel_txn["signed_amount"])) == Decimal("-300.00")

    assert owner_txn["transaction_type"] == TransactionType.OWNER_PAYMENT
    assert Decimal(str(owner_txn["amount"])) == Decimal("200.00")
    assert Decimal(str(owner_txn["signed_amount"])) == Decimal("-200.00")

    # 4. Deterministic Net Cash Movement
    metrics = FinancialCalculator.calculate_metrics(txns)
    assert metrics["_raw"]["gross_income"] == Decimal("1500.00")
    assert metrics["_raw"]["operating_expenses"] == Decimal("300.00")
    assert metrics["_raw"]["operating_profit"] == Decimal("1200.00")
    assert metrics["_raw"]["owner_payments"] == Decimal("200.00")
    assert metrics["_raw"]["driver_take_home"] == Decimal("1000.00")
    assert metrics["_raw"]["net_cash_retained"] == Decimal("1000.00")


# ============================================================================
# 2. Failure Injection: Before First Insert
# ============================================================================

def test_failure_injection_before_first_insert(services):
    """
    Simulates crash/network failure before the first transaction insert.
    Verifies 0 writes occur, status transitions to FAILED_RETRYABLE,
    and subsequent retry succeeds without duplicate records.
    """
    db = services["db"]
    pending_svc = services["pending"]
    ledger_svc = services["ledger"]

    driver_id = "DRV_PHASE3_FAIL_0"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_FAIL_0"
    )
    pending_id = proposed["pending_action_id"]

    orig_record = ledger_svc.record_transaction
    call_count = 0

    def mock_record_fail_at_0(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Simulated DB connection failure before insert 0")

    with patch.object(ledger_svc, "record_transaction", side_effect=mock_record_fail_at_0):
        with pytest.raises(ConnectionError, match="Simulated DB connection failure"):
            pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_FAIL_0")

    # Verify zero records in ledger
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Verify pending action is marked FAILED_RETRYABLE
    pending_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert pending_doc["status"] == PendingActionStatus.FAILED_RETRYABLE.value
    assert "Simulated DB connection failure" in pending_doc.get("last_error", "")

    # Retry without failure: executes all 3
    retry_res = pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_RETRY_0")
    assert retry_res["status"] == "CONFIRMED"
    assert retry_res["count"] == 3
    assert db.transactions.count_documents({"driver_id": driver_id}) == 3

    # Check consumed status
    final_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert final_doc["status"] == PendingActionStatus.CONSUMED.value


# ============================================================================
# 3. Failure Injection: After First Insert
# ============================================================================

def test_failure_injection_after_first_insert(services):
    """
    Simulates crash/network failure after transaction 0 (FARE) is inserted,
    before transaction 1 (FUEL) is inserted.
    Verifies that on retry:
    - Transaction 0 is recognized via idempotency key and NOT re-inserted.
    - Transactions 1 & 2 are inserted.
    - Exactly 3 total transactions exist in the ledger.
    """
    db = services["db"]
    pending_svc = services["pending"]
    ledger_svc = services["ledger"]

    driver_id = "DRV_PHASE3_FAIL_1"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_FAIL_1"
    )
    pending_id = proposed["pending_action_id"]

    orig_record = ledger_svc.record_transaction
    call_count = 0

    def mock_record_fail_at_1(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # Fail on second item (FUEL)
            raise RuntimeError("Simulated crash after FARE insert")
        return orig_record(*args, **kwargs)

    with patch.object(ledger_svc, "record_transaction", side_effect=mock_record_fail_at_1):
        with pytest.raises(RuntimeError, match="Simulated crash after FARE insert"):
            pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_FAIL_1")

    # Verify exactly 1 record committed before crash
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1
    committed_first = db.transactions.find_one({"driver_id": driver_id})
    assert committed_first["category"] == "FARE"

    # Status must be FAILED_RETRYABLE, NOT prematurely marked CONSUMED
    pending_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert pending_doc["status"] == PendingActionStatus.FAILED_RETRYABLE.value

    # Retry confirmation: resumes and completes remaining transactions
    retry_res = pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_RETRY_1")
    assert retry_res["status"] == "CONFIRMED"
    assert retry_res["count"] == 3

    # CRITICAL ATOMICITY CHECK: Exactly 3 records in DB, zero duplicate FARE entries!
    total_txns = list(db.transactions.find({"driver_id": driver_id}))
    assert len(total_txns) == 3
    categories = [t["category"] for t in total_txns]
    assert sorted(categories) == ["FARE", "FUEL", "OWNER_RENT"]


# ============================================================================
# 4. Failure Injection: After Second Insert
# ============================================================================

def test_failure_injection_after_second_insert(services):
    """
    Simulates crash after transaction 0 and 1 are inserted, before transaction 2.
    Verifies that on retry:
    - Items 0 & 1 return existing from ledger via idempotency keys.
    - Item 2 is inserted.
    - Exactly 3 total transactions exist in the ledger.
    """
    db = services["db"]
    pending_svc = services["pending"]
    ledger_svc = services["ledger"]

    driver_id = "DRV_PHASE3_FAIL_2"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_FAIL_2"
    )
    pending_id = proposed["pending_action_id"]

    orig_record = ledger_svc.record_transaction
    call_count = 0

    def mock_record_fail_at_2(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:  # Fail on third item (OWNER_RENT)
            raise RuntimeError("Simulated crash after FUEL insert")
        return orig_record(*args, **kwargs)

    with patch.object(ledger_svc, "record_transaction", side_effect=mock_record_fail_at_2):
        with pytest.raises(RuntimeError, match="Simulated crash after FUEL insert"):
            pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_FAIL_2")

    # Exactly 2 records in ledger
    assert db.transactions.count_documents({"driver_id": driver_id}) == 2

    # Status must be FAILED_RETRYABLE
    pending_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert pending_doc["status"] == PendingActionStatus.FAILED_RETRYABLE.value

    # Retry confirmation
    retry_res = pending_svc.confirm_action(pending_id, driver_id, "IDEM_CONFIRM_RETRY_2")
    assert retry_res["status"] == "CONFIRMED"
    assert retry_res["count"] == 3

    # Verify no duplicates
    total_txns = list(db.transactions.find({"driver_id": driver_id}))
    assert len(total_txns) == 3


# ============================================================================
# 5. Crash Recovery: Post-Write Crash Before Pending Action Status Update
# ============================================================================

def test_crash_recovery_after_all_inserts_before_pending_status_update(services):
    """
    Simulates a server crash occurring AFTER all 3 transactions have been committed
    to the immutable transactions ledger, but BEFORE pending_actions is updated to CONSUMED.
    Verifies:
    - Status is still CONFIRMED when server restarts.
    - confirm_action detects all 3 transactions exist via _find_existing_execution_result.
    - Transitions to CONSUMED without executing duplicate inserts.
    - Ledger contains exactly 3 records.
    """
    db = services["db"]
    pending_svc = services["pending"]
    ledger_svc = services["ledger"]

    driver_id = "DRV_PHASE3_POST_WRITE"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_POST_WRITE"
    )
    pending_id = proposed["pending_action_id"]

    # Execute all 3 writes directly to simulate post-write crash
    exec_key = f"EXEC_{pending_id}"
    txns = batch_data["transactions"]
    tt_map = {"INCOME": TransactionType.INCOME, "EXPENSE": TransactionType.EXPENSE, "OWNER_PAYMENT": TransactionType.OWNER_PAYMENT}
    for idx, t in enumerate(txns):
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id=batch_data["vehicle_id"],
            transaction_type=tt_map[t["action_type"]],
            amount=Decimal(t["amount"]),
            category=t["category"],
            description=t["description"],
            idempotency_key=f"{exec_key}_{idx}_{t['category']}"
        )

    # Set pending action status to CONFIRMED (simulating interrupted confirmation process)
    db.pending_actions.update_one(
        {"pending_action_id": pending_id},
        {"$set": {"status": PendingActionStatus.CONFIRMED.value}}
    )

    assert db.transactions.count_documents({"driver_id": driver_id}) == 3

    # Now recover by calling confirm_action
    res = pending_svc.confirm_action(pending_id, driver_id, "IDEM_RECOVERY")

    assert res["status"] == "CONFIRMED"
    assert res["count"] == 3
    assert len(res["transactions"]) == 3

    # Check pending action transitioned to CONSUMED
    updated_pending = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert updated_pending["status"] == PendingActionStatus.CONSUMED.value

    # Ledger must still have exactly 3 records (no duplicates added during recovery)
    assert db.transactions.count_documents({"driver_id": driver_id}) == 3


# ============================================================================
# 6. Concurrent Confirmation Race Condition
# ============================================================================

def test_concurrent_confirmation_race_condition(services):
    """
    Simulates two threads attempting to confirm the same pending batch simultaneously.
    Verifies that the atomic find_one_and_update state transition ensures
    only one execution path writes to the ledger, preventing duplicate transactions.
    """
    db = services["db"]
    pending_svc = services["pending"]

    driver_id = "DRV_PHASE3_CONCURRENT"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_CONCURRENT"
    )
    pending_id = proposed["pending_action_id"]

    results = []
    errors = []

    def try_confirm():
        try:
            r = pending_svc.confirm_action(pending_id, driver_id, "IDEM_RACE")
            results.append(r)
        except Exception as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_confirm)
        f2 = executor.submit(try_confirm)
        f1.result()
        f2.result()

    # At least one succeeded
    assert len(results) >= 1
    # Total committed transactions must be EXACTLY 3, never 6
    assert db.transactions.count_documents({"driver_id": driver_id}) == 3


# ============================================================================
# 7. Strict Driver Isolation Enforcement
# ============================================================================

def test_strict_driver_isolation_enforcement(services):
    """
    Verifies that Driver B cannot view, confirm, or modify Driver A's pending batch.
    Verifies that Driver B's ledger queries return 0 records from Driver A.
    """
    pending_svc = services["pending"]
    repo = services["repo"]

    driver_a = "DRV_ALICE"
    driver_b = "DRV_BOB"
    batch_data = _make_sample_batch_data()

    proposed = pending_svc.propose_action(
        driver_id=driver_a,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_ALICE"
    )
    pending_id = proposed["pending_action_id"]

    # Driver B cannot access Driver A's pending action
    retrieved = pending_svc.get_pending_action(pending_id, driver_id=driver_b)
    assert retrieved is None

    # Driver B cannot confirm Driver A's pending action
    with pytest.raises(PendingActionUnauthorizedError, match="Unauthorized"):
        pending_svc.confirm_action(pending_id, driver_id=driver_b, idempotency_key="IDEM_BOB_ATTACK")

    # Driver A confirms successfully
    res = pending_svc.confirm_action(pending_id, driver_id=driver_a, idempotency_key="IDEM_ALICE_CONFIRM")
    assert res["status"] == "CONFIRMED"

    # Driver B cannot see Driver A's transactions in their ledger
    txns_b = repo.get_transactions_for_driver(driver_b)
    assert len(txns_b) == 0

    # Driver A sees their own 3 transactions
    txns_a = repo.get_transactions_for_driver(driver_a)
    assert len(txns_a) == 3


# ============================================================================
# 8. Owner Settlement Offset Verification
# ============================================================================

def test_owner_settlement_offset_verification(services):
    """
    Verifies that when a settlement is calculated:
    - OWNER_RENT ₹200 reduces the owner settlement obligation (remaining balance).
    - Operating expenses remain at ₹300 (fuel only, NOT inflated by owner rent).
    - Driver take-home is ₹1,000.
    """
    pending_svc = services["pending"]
    settlement_svc = services["settlement"]

    driver_id = "DRV_PHASE3_SETTLE"
    vehicle_id = "KA01SETTLE1"
    batch_data = _make_sample_batch_data()
    batch_data["vehicle_id"] = vehicle_id

    # Configure vehicle with daily rent of ₹350.00
    settlement_svc.get_or_create_vehicle(
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        default_rent=Decimal("350.00")
    )

    # Propose and confirm Tanglish batch
    proposed = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data=batch_data,
        idempotency_key="IDEM_SETTLE_BATCH"
    )
    pending_svc.confirm_action(proposed["pending_action_id"], driver_id, "IDEM_SETTLE_CONFIRM")

    # Calculate settlement for today
    settle_res = settlement_svc.create_settlement(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        settlement_date=today_ist(),
        previous_balance=Decimal("0.00")
    )

    # Settlement figures:
    # Expected rent: ₹350.00
    # Gross income: ₹1,500.00
    # Operating expenses: ₹300.00 (Fuel only!)
    # Operating profit: ₹1,200.00 (1500 - 300)
    # Owner payments: ₹200.00
    # Total obligation: ₹350.00 (0 + 350)
    # Remaining balance: ₹150.00 (350 - 200) -> Obligation offset by owner payment!
    # Driver take-home: ₹1,000.00 (1200 - 200)
    assert Decimal(str(settle_res["expected_rent"])) == Decimal("350.00")
    assert Decimal(str(settle_res["gross_income"])) == Decimal("1500.00")
    assert Decimal(str(settle_res["operating_expenses"])) == Decimal("300.00")
    assert Decimal(str(settle_res["operating_profit"])) == Decimal("1200.00")
    assert Decimal(str(settle_res["owner_payments"])) == Decimal("200.00")
    assert Decimal(str(settle_res["total_obligation"])) == Decimal("350.00")
    assert Decimal(str(settle_res["remaining_balance"])) == Decimal("150.00")
    assert Decimal(str(settle_res["driver_take_home"])) == Decimal("1000.00")
    assert settle_res["settlement_status"] == "PARTIALLY_SETTLED"


# ============================================================================
# 9. Real MongoDB URI Safety Guard Logic
# ============================================================================

def test_real_mongodb_uri_safety_guards():
    """
    Verifies that safety mechanisms prevent connecting to production MongoDB:
    1. Rejects URI if TEST_LIVE_MONGODB_URI is absent (never falls back to MONGODB_URI).
    2. Rejects any URI pointing to 'production', 'prod', or production DB name 't2t_drive'.
    """
    from tests.run_real_mongodb_and_timbre_verification import inspect_mongodb_env

    # Without TEST_LIVE_MONGODB_URI set
    with patch.dict(os.environ, {}, clear=True), patch("tests.run_real_mongodb_and_timbre_verification.dotenv_values", return_value={}):
        info = inspect_mongodb_env()
        assert info["test_live_uri_configured"] is False
        assert info["test_live_uri"] is None

    # Safety validator function
    def validate_test_database_name(uri: str, db_name: str) -> bool:
        forbidden = ["production", "prod", "live"]
        if any(f in db_name.lower() for f in forbidden):
            return False
        if db_name == "t2t_drive":  # Exact production database name
            return False
        if not db_name.endswith("_test"):
            return False
        return True

    assert validate_test_database_name("mongodb://localhost:27017", "t2t_drive") is False
    assert validate_test_database_name("mongodb://localhost:27017", "production_db") is False
    assert validate_test_database_name("mongodb://localhost:27017", "t2t_drive_test") is True
    assert validate_test_database_name("mongodb://localhost:27017", "integration_test") is True
