"""
T2T-DRIVE — Comprehensive Financial Integrity & Recovery Test Suite.
Workstream D: Financial Correctness, BSON Decimal128 Precision, Idempotency & Concurrency.

Covers:
1. Strict confirmation requirement: Zero writes prior to explicit driver confirmation
2. Rejection safety: Zero writes upon driver cancellation
3. Exact monetary precision: BSON Decimal128 and Python Decimal avoid IEEE-754 float drift
4. Idempotency guarantee: Replayed requests return cached result without double billing
5. Concurrent confirmation prevention: Atomic single-winner state machine
6. Partial batch recovery: Individual category confirmation within multi-item batches
"""

import threading
from decimal import Decimal
import pytest
from bson.decimal128 import Decimal128

from app import create_app
from app.models.financial import PendingActionType, TransactionType
from app.services.pending_action_service import (
    PendingActionAlreadyConsumedError,
    PendingActionCancelledError
)


@pytest.fixture
def app_instance():
    app = create_app("testing")
    return app


class TestFinancialIntegrityAndRecovery:
    """Rigorous audit of financial state machines, immutability, and ledger integrity."""

    def test_01_zero_writes_before_confirmation(self, app_instance):
        """Proposing an action MUST NOT write any record to the immutable transactions collection."""
        db = app_instance.extensions["db"]
        pending_svc = app_instance.extensions["pending_action_service"]
        driver_id = "DRV_FIN_001"

        # Count transactions before
        tx_count_before = db.transactions.count_documents({"driver_id": driver_id})

        # Step 1: Propose expense of 450.00
        proposal = pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_EXPENSE,
            proposed_data={
                "amount": "450.00",
                "category": "FUEL",
                "vehicle_id": "TN-01-AB-1234",
                "notes": "Diesel fill"
            },
            idempotency_key="IDEMP_FIN_01"
        )
        assert proposal["status"] == "PENDING"
        pending_id = proposal["pending_action_id"]

        # Verification: ledger MUST still have exactly 0 transactions
        tx_count_middle = db.transactions.count_documents({"driver_id": driver_id})
        assert tx_count_middle == tx_count_before

        # Step 2: Driver confirms action
        confirm_res = pending_svc.confirm_action(
            pending_action_id=pending_id,
            driver_id=driver_id,
            idempotency_key="IDEMP_CONFIRM_FIN_01"
        )
        assert confirm_res["status"] == "COMPLETED"

        # Verification: now exactly 1 transaction exists
        tx_count_after = db.transactions.count_documents({"driver_id": driver_id})
        assert tx_count_after == tx_count_before + 1

    def test_02_zero_writes_on_cancellation(self, app_instance):
        """Cancelled actions transition to CANCELLED and write nothing to the ledger."""
        db = app_instance.extensions["db"]
        pending_svc = app_instance.extensions["pending_action_service"]
        driver_id = "DRV_FIN_002"

        tx_count_before = db.transactions.count_documents({"driver_id": driver_id})

        # Propose
        proposal = pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_INCOME,
            proposed_data={"amount": "1200.00", "category": "FARE", "vehicle_id": "TN-01-AB-1234"},
            idempotency_key="IDEMP_FIN_02"
        )
        pending_id = proposal["pending_action_id"]

        # Cancel
        pending_svc.cancel_action(pending_action_id=pending_id, driver_id=driver_id, reason="Mistake")

        # Confirm ledger is untouched
        tx_count_after = db.transactions.count_documents({"driver_id": driver_id})
        assert tx_count_after == tx_count_before

        # Ensure subsequent attempt to confirm cancelled action is strictly rejected
        with pytest.raises(PendingActionCancelledError):
            pending_svc.confirm_action(
                pending_action_id=pending_id,
                driver_id=driver_id,
                idempotency_key="IDEMP_CONFIRM_FAIL"
            )

    def test_03_exact_decimal_precision(self, app_instance):
        """Verifies exact financial arithmetic without binary floating-point round-off error."""
        ledger_svc = app_instance.extensions["ledger_service"]
        db = app_instance.extensions["db"]
        driver_id = "DRV_FIN_003"

        # Record series of small fractional transactions: 70.10, 80.20, 50.30
        amounts = [Decimal("70.10"), Decimal("80.20"), Decimal("50.30")]
        expected_sum = Decimal("200.60")

        for idx, amt in enumerate(amounts):
            ledger_svc.record_transaction(
                driver_id=driver_id,
                vehicle_id="TN-01-AB-1234",
                transaction_type=TransactionType.EXPENSE,
                amount=amt,
                category="FOOD",
                description="Food expense",
                idempotency_key=f"IDEMP_DEC_{idx}"
            )

        # Retrieve and verify total sum matches exact 200.60 without float jitter
        txns = ledger_svc.repo.get_transactions_for_driver(driver_id=driver_id)
        calculated_sum = sum(t["amount"] for t in txns)
        assert calculated_sum == expected_sum
        assert str(calculated_sum) == "200.60"

    def test_04_idempotent_reexecution_safety(self, app_instance):
        """Re-submitting confirm_action with the same idempotency key returns cached result."""
        pending_svc = app_instance.extensions["pending_action_service"]
        db = app_instance.extensions["db"]
        driver_id = "DRV_FIN_004"

        proposal = pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_EXPENSE,
            proposed_data={"amount": "300.00", "category": "FUEL", "vehicle_id": "TN-01-AB-1234"},
            idempotency_key="IDEMP_FIN_04"
        )
        pending_id = proposal["pending_action_id"]

        exec_key = "IDEMP_EXEC_04"

        # First confirmation
        res1 = pending_svc.confirm_action(pending_action_id=pending_id, driver_id=driver_id, idempotency_key=exec_key)
        assert res1["status"] == "COMPLETED"

        tx_count_1 = db.transactions.count_documents({"driver_id": driver_id})

        # Second confirmation with same key (replay scenario)
        res2 = pending_svc.confirm_action(pending_action_id=pending_id, driver_id=driver_id, idempotency_key=exec_key)
        assert res2["status"] == "COMPLETED"

        # Ledger MUST not contain duplicate transactions
        tx_count_2 = db.transactions.count_documents({"driver_id": driver_id})
        assert tx_count_2 == tx_count_1

    def test_05_concurrent_confirmation_race_prevention(self, app_instance):
        """Concurrent confirm requests for the same pending action never double-write."""
        pending_svc = app_instance.extensions["pending_action_service"]
        db = app_instance.extensions["db"]
        driver_id = "DRV_FIN_005"

        proposal = pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_EXPENSE,
            proposed_data={"amount": "250.00", "category": "TOLL", "vehicle_id": "TN-01-AB-1234"},
            idempotency_key="IDEMP_FIN_05"
        )
        pending_id = proposal["pending_action_id"]

        results = []
        errors = []

        def worker(key):
            try:
                res = pending_svc.confirm_action(
                    pending_action_id=pending_id,
                    driver_id=driver_id,
                    idempotency_key=key
                )
                results.append(res)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=("KEY_RACE_1",))
        t2 = threading.Thread(target=worker, args=("KEY_RACE_2",))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both callers get valid completion responses or idempotency safety
        assert len(results) + len(errors) == 2

        # Crucial financial guarantee: Exactly 1 transaction exists in the database
        assert db.transactions.count_documents({"driver_id": driver_id}) == 1

    def test_06_partial_batch_recovery(self, app_instance):
        """Driver can confirm only a specific item (e.g. FUEL) from a multi-item batch proposal."""
        pending_svc = app_instance.extensions["pending_action_service"]
        db = app_instance.extensions["db"]
        driver_id = "DRV_FIN_006"

        batch_items = [
            {"action_type": "ADD_INCOME", "category": "FARE", "amount": 1000.00, "description": "Collection"},
            {"action_type": "ADD_EXPENSE", "category": "FUEL", "amount": 350.00, "description": "Petrol"},
            {"action_type": "ADD_OWNER_PAYMENT", "category": "OWNER_RENT", "amount": 200.00, "description": "Rent"}
        ]

        proposal = pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
            proposed_data={"transactions": batch_items, "vehicle_id": "TN-01-AB-1234"},
            idempotency_key="IDEMP_BATCH_01"
        )
        pending_id = proposal["pending_action_id"]

        # Confirm ONLY the FUEL item
        res = pending_svc.confirm_action(
            pending_action_id=pending_id,
            driver_id=driver_id,
            idempotency_key="IDEMP_PARTIAL_CONFIRM",
            filter_category="FUEL"
        )
        assert res["status"] == "CONFIRMED"
        assert res.get("is_partial") is True

        # Exactly 1 transaction (the FUEL one) was recorded
        driver_txns = list(db.transactions.find({"driver_id": driver_id}))
        assert len(driver_txns) == 1
        assert driver_txns[0]["category"] == "FUEL"
        assert Decimal(str(driver_txns[0]["amount"])) == Decimal("350.00")
