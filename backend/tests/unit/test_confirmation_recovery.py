"""
Unit tests for Crash-Recovery and Idempotency in Pending-Action Confirmation (Critical Correction B).
Simulates crashes before and after ledger writes, concurrent double confirmations,
transient retryable failures, and strict driver authorization.
"""

import pytest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from app.models.financial import PendingActionType, PendingActionStatus, TransactionType
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.pending_action_service import (
    PendingActionService,
    PendingActionUnauthorizedError,
    PendingActionExpiredError,
    PendingActionCancelledError
)


def test_recovery_when_interrupted_before_ledger_write(db):
    """
    Simulates a server crash right after setting status = CONFIRMED,
    BEFORE the ledger transaction was committed.
    On retry, the recovery engine detects that no ledger write occurred,
    executes the transaction safely, and marks CONSUMED.
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    driver_id = "DRV_REC_1"
    prop = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_EXPENSE,
        proposed_data={"vehicle_id": "VEH_1", "amount": "400.00", "category": "FUEL"},
        idempotency_key="CRASH_BEFORE_KEY"
    )
    pending_id = prop["pending_action_id"]

    # SIMULATE CRASH: Mark action CONFIRMED manually (as if worker died before write)
    db.pending_actions.update_one(
        {"pending_action_id": pending_id},
        {"$set": {"status": PendingActionStatus.CONFIRMED.value}}
    )

    # Verify no transaction in ledger yet
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # RETRY: Driver calls confirm_action after server restart
    recovered_res = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key="RETRY_CONF_KEY"
    )

    # Must succeed, write the transaction, and mark CONSUMED!
    assert "transaction_id" in recovered_res
    assert recovered_res["amount"] == "400.00"
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1

    action_after = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert action_after["status"] == PendingActionStatus.CONSUMED.value


def test_recovery_when_interrupted_after_ledger_write(db):
    """
    Simulates a server crash AFTER the ledger write was committed to MongoDB,
    but before the pending action was marked CONSUMED.
    On retry, the recovery engine detects the existing ledger transaction,
    avoids creating a duplicate, marks CONSUMED, and returns the original transaction.
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    driver_id = "DRV_REC_2"
    prop = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_INCOME,
        proposed_data={"vehicle_id": "VEH_1", "amount": "750.00", "category": "FARE"},
        idempotency_key="CRASH_AFTER_PROP"
    )
    pending_id = prop["pending_action_id"]
    exec_key = f"EXEC_{pending_id}"

    # SIMULATE PRE-CRASH STATE:
    # 1. Action is in CONFIRMED
    db.pending_actions.update_one(
        {"pending_action_id": pending_id},
        {"$set": {"status": PendingActionStatus.CONFIRMED.value}}
    )
    # 2. Transaction WAS committed to ledger
    committed_txn = ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="VEH_1",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("750.00"),
        category="FARE",
        description="Airport fare",
        idempotency_key=exec_key
    )

    # Currently 1 transaction exists
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1

    # RETRY: Driver retries confirm_action
    recovered = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key="RETRY_KEY_2"
    )

    # Must return the committed transaction ID without creating a duplicate!
    assert recovered["transaction_id"] == committed_txn["transaction_id"]
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1  # ZERO DUPLICATES!

    # Action is now CONSUMED
    action_after = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert action_after["status"] == PendingActionStatus.CONSUMED.value


def test_concurrent_confirmations_prevent_duplicate_writes(db):
    """
    Simulates 4 simultaneous HTTP requests hitting confirm_action for the same pending action.
    Atomicity guarantees that exactly ONE write occurs and no duplicates are created.
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    driver_id = "DRV_CONC_CONF"
    prop = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_EXPENSE,
        proposed_data={"vehicle_id": "VEH_1", "amount": "250.00", "category": "PARKING"},
        idempotency_key="CONC_PROP"
    )
    pending_id = prop["pending_action_id"]

    results = []
    errors = []

    def _try_confirm(i):
        try:
            return pending_svc.confirm_action(pending_id, driver_id, f"CONF_KEY_{i}")
        except Exception as e:
            return e

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(_try_confirm, range(4)))

    successes = [o for o in outcomes if isinstance(o, dict) and "transaction_id" in o]

    # At least one succeeded, and all successful responses reference the EXACT SAME transaction_id!
    assert len(successes) >= 1
    txn_ids = {s["transaction_id"] for s in successes}
    assert len(txn_ids) == 1  # Exactly one unique transaction ID!

    # Verify database has exactly ONE transaction
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1


def test_failed_retryable_workflow(db):
    """
    When an unexpected error occurs during confirmation, the action transitions
    to FAILED_RETRYABLE rather than being stuck in CONFIRMED.
    The driver can subsequently retry and succeed.
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    driver_id = "DRV_TRANSIENT"
    prop = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_INCOME,
        proposed_data={"vehicle_id": "VEH_1", "amount": "900.00", "category": "FARE"},
        idempotency_key="TRANSIENT_PROP"
    )
    pending_id = prop["pending_action_id"]

    # Monkeypatch ledger.record_transaction to fail once with transient DB error
    original_record = ledger.record_transaction
    fail_flag = [True]

    def _flaky_record(*args, **kwargs):
        if fail_flag[0]:
            fail_flag[0] = False
            raise ConnectionError("Transient MongoDB network disconnect")
        return original_record(*args, **kwargs)

    ledger.record_transaction = _flaky_record

    # First attempt fails
    with pytest.raises(ConnectionError):
        pending_svc.confirm_action(pending_id, driver_id, "CONF_TRY_1")

    # Action status must be FAILED_RETRYABLE (not permanently stuck!)
    action_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert action_doc["status"] == PendingActionStatus.FAILED_RETRYABLE.value
    assert "Transient MongoDB network disconnect" in action_doc["last_error"]

    # Second attempt succeeds!
    res = pending_svc.confirm_action(pending_id, driver_id, "CONF_TRY_2")
    assert res["amount"] == "900.00"
    assert db.transactions.count_documents({"driver_id": driver_id}) == 1
