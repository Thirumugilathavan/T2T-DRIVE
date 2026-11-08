"""
Unit tests for Append-Only Ledger Service and Transaction Repository.
Ensures completed transactions cannot be altered or deleted, and verifies
reversal and adjustment workflows.
"""

import pytest
from decimal import Decimal
from app.models.financial import TransactionType
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.audit_service import AuditService


def test_record_transactions(db):
    repo = TransactionRepository(db)
    audit = AuditService(db)
    ledger = LedgerService(repo=repo, audit_service=audit)

    # 1. Record Income
    inc = ledger.record_transaction(
        driver_id="DRV_101",
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("1200.00"),
        category="FARE",
        description="Airport drop",
        idempotency_key="KEY_INC_1"
    )
    assert inc["amount"] == "1200.00"
    assert inc["signed_amount"] == "1200.00"
    assert inc["status"] == "COMPLETED"

    # 2. Record Expense
    exp = ledger.record_transaction(
        driver_id="DRV_101",
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("350.00"),
        category="FUEL",
        description="CNG fill",
        idempotency_key="KEY_EXP_1"
    )
    assert exp["amount"] == "350.00"
    assert exp["signed_amount"] == "-350.00"

    # 3. Verify in repository
    retrieved = ledger.get_transaction(inc["transaction_id"], driver_id="DRV_101")
    assert retrieved is not None
    assert retrieved["transaction_id"] == inc["transaction_id"]


def test_reversal_preserves_original(db):
    repo = TransactionRepository(db)
    audit = AuditService(db)
    ledger = LedgerService(repo=repo, audit_service=audit)

    # 1. Create original expense of ₹500
    orig = ledger.record_transaction(
        driver_id="DRV_102",
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("500.00"),
        category="FUEL",
        description="Mistaken duplicate fuel entry",
        idempotency_key="KEY_ORIG_REV"
    )
    orig_id = orig["transaction_id"]

    # 2. Create reversal
    rev = ledger.create_reversal(
        original_txn_id=orig_id,
        driver_id="DRV_102",
        reason="Entered wrong amount by mistake",
        idempotency_key="KEY_REV_1"
    )
    assert rev["transaction_type"] == "EXPENSE_REVERSAL"
    assert rev["amount"] == "500.00"
    assert rev["signed_amount"] == "500.00"  # Positive to offset negative expense!
    assert rev["reference_id"] == orig_id

    # 3. VERIFY ORIGINAL RECORD IS COMPLETELY PRESERVED AND UNCHANGED
    orig_after = ledger.get_transaction(orig_id, driver_id="DRV_102")
    assert orig_after["amount"] == "500.00"
    assert orig_after["signed_amount"] == "-500.00"
    assert orig_after["status"] == "COMPLETED"  # Status remains COMPLETED

    # 4. Attempting to reverse again must fail
    with pytest.raises(ValueError) as exc:
        ledger.create_reversal(
            original_txn_id=orig_id,
            driver_id="DRV_102",
            reason="Second reversal attempt",
            idempotency_key="KEY_REV_2"
        )
    assert "has already been reversed" in str(exc.value)


def test_adjustment_workflow(db):
    """
    Specification requirement:
    Original expense: ₹500
    Correction required: ₹450
    Result:
    Original: -₹500
    Reversal: +₹500
    Corrected: -₹450
    Net expense: ₹450
    """
    repo = TransactionRepository(db)
    audit = AuditService(db)
    ledger = LedgerService(repo=repo, audit_service=audit)

    # Create original expense
    orig = ledger.record_transaction(
        driver_id="DRV_103",
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("500.00"),
        category="FUEL",
        description="Fuel receipt",
        idempotency_key="KEY_ADJ_ORIG"
    )
    orig_id = orig["transaction_id"]

    # Execute adjustment
    adj = ledger.create_adjustment(
        original_txn_id=orig_id,
        driver_id="DRV_103",
        new_amount=Decimal("450.00"),
        reason="Typo in receipt: actual bill was 450",
        idempotency_key="KEY_ADJ_1"
    )
    assert adj["status"] == "ADJUSTED"
    assert adj["reversal"]["signed_amount"] == "500.00"
    assert adj["corrected_transaction"]["signed_amount"] == "-450.00"

    # Query all driver transactions and compute net
    txns = repo.find_transactions(driver_id="DRV_103")
    assert len(txns) == 3
    net_expense = sum(t["signed_amount"] for t in txns)
    assert net_expense == Decimal("-450.00")


def test_driver_isolation(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)

    txn_a = ledger.record_transaction(
        driver_id="DRV_AAA",
        vehicle_id="VEH_A",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("1000.00"),
        category="FARE",
        description="Trip A",
        idempotency_key="KEY_AAA"
    )

    # Driver B cannot look up Driver A's transaction
    doc_b = ledger.get_transaction(txn_a["transaction_id"], driver_id="DRV_BBB")
    assert doc_b is None

    # Driver B cannot reverse Driver A's transaction
    with pytest.raises(ValueError) as exc:
        ledger.create_reversal(
            original_txn_id=txn_a["transaction_id"],
            driver_id="DRV_BBB",
            reason="Malicious reversal attempt",
            idempotency_key="KEY_MAL"
        )
    assert "not found or does not belong to driver" in str(exc.value)
