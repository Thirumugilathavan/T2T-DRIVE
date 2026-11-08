"""
Unit tests for Pending-Action and Confirmation Workflow.
Ensures that no financial write occurs without explicit driver confirmation,
and verifies expiration, cancellation, and driver isolation rules.
"""

import pytest
import datetime
from decimal import Decimal
from app.models.financial import PendingActionType
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.pending_action_service import (
    PendingActionService,
    PendingActionExpiredError,
    PendingActionCancelledError,
    PendingActionAlreadyConsumedError,
    PendingActionUnauthorizedError
)
from app.services.audit_service import AuditService


def test_pending_action_confirmation_lifecycle(db):
    audit = AuditService(db)
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo, audit_service=audit)
    pending_svc = PendingActionService(db=db, ledger_service=ledger, audit_service=audit)

    driver_id = "DRV_PEND_1"
    proposed_data = {
        "vehicle_id": "KA01AB1234",
        "amount": "600.00",
        "category": "FUEL",
        "description": "Petrol pump receipt"
    }

    # 1. Propose action -> Status must be PENDING
    prop = pending_svc.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_EXPENSE,
        proposed_data=proposed_data,
        idempotency_key="KEY_PROP_1"
    )
    pending_id = prop["pending_action_id"]
    assert prop["status"] == "PENDING"
    assert "Confirm recording expense" in prop["human_readable_summary"]

    # 2. Verify that NO transaction exists yet in the ledger!
    txns = repo.find_transactions(driver_id=driver_id)
    assert len(txns) == 0

    # 3. Confirm action -> Status becomes CONSUMED and transaction is written
    result = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key="KEY_CONF_1"
    )
    assert "transaction_id" in result
    assert result["amount"] == "600.00"
    assert result["signed_amount"] == "-600.00"

    # 4. Verify transaction exists in ledger now!
    txns_after = repo.find_transactions(driver_id=driver_id)
    assert len(txns_after) == 1

    # 5. Replay confirmation -> Must return cached execution result safely
    replay = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key="KEY_CONF_1"
    )
    assert replay["transaction_id"] == result["transaction_id"]


def test_cross_driver_confirmation_rejected(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    # Driver A proposes
    prop = pending_svc.propose_action(
        driver_id="DRV_ALICE",
        action_type=PendingActionType.ADD_INCOME,
        proposed_data={"vehicle_id": "VEH_1", "amount": "500.00", "category": "FARE"},
        idempotency_key="KEY_ALICE"
    )

    # Driver B attempts to confirm Driver A's action -> MUST RAISE PendingActionUnauthorizedError!
    with pytest.raises(PendingActionUnauthorizedError):
        pending_svc.confirm_action(
            pending_action_id=prop["pending_action_id"],
            driver_id="DRV_BOB",
            idempotency_key="KEY_BOB"
        )


def test_expired_action_rejected(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    prop = pending_svc.propose_action(
        driver_id="DRV_EXP",
        action_type=PendingActionType.ADD_INCOME,
        proposed_data={"vehicle_id": "VEH_1", "amount": "500.00", "category": "FARE"},
        idempotency_key="KEY_EXP_PROP"
    )
    pending_id = prop["pending_action_id"]

    # Backdate expiration time to 20 minutes ago
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
    db.pending_actions.update_one(
        {"pending_action_id": pending_id},
        {"$set": {"expires_at": past_time}}
    )

    # Confirmation must raise PendingActionExpiredError
    with pytest.raises(PendingActionExpiredError):
        pending_svc.confirm_action(pending_id, driver_id="DRV_EXP", idempotency_key="KEY_EXP_CONF")


def test_cancelled_action_rejected(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    pending_svc = PendingActionService(db=db, ledger_service=ledger)

    prop = pending_svc.propose_action(
        driver_id="DRV_CANC",
        action_type=PendingActionType.ADD_EXPENSE,
        proposed_data={"vehicle_id": "VEH_1", "amount": "200.00", "category": "FOOD"},
        idempotency_key="KEY_CANC_PROP"
    )
    pending_id = prop["pending_action_id"]

    # Cancel action
    cancel_res = pending_svc.cancel_action(pending_id, driver_id="DRV_CANC", reason="Driver changed mind")
    assert cancel_res["status"] == "CANCELLED"

    # Confirmation must raise PendingActionCancelledError
    with pytest.raises(PendingActionCancelledError):
        pending_svc.confirm_action(pending_id, driver_id="DRV_CANC", idempotency_key="KEY_CANC_CONF")
