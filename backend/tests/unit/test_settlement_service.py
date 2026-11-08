"""
Unit tests for Owner-Driver Settlement and Reconciliation Engine.
Verifies deterministic calculations, versioning, history preservation,
and ledger single-source-of-truth reconciliation.
"""

import pytest
from decimal import Decimal
from app.models.financial import TransactionType
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.settlement_service import SettlementService
from app.services.audit_service import AuditService


def test_settlement_creation_and_reconciliation(db):
    audit = AuditService(db)
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo, audit_service=audit)
    settle_svc = SettlementService(db=db, repo=repo, audit_service=audit)

    driver_id = "DRV_SETTLE_1"
    vehicle_id = "KA02CD5678"
    date_str = "2026-11-08"

    # Setup vehicle with ₹350 daily rent
    settle_svc.get_or_create_vehicle(vehicle_id, driver_id, default_rent=Decimal("350.00"))

    # Record transactions in ledger:
    # Gross income = 2000
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.INCOME,
        amount=Decimal("2000.00"),
        category="FARE",
        description="Daily fares",
        transaction_date=date_str,
        idempotency_key="ST_TXN_1"
    )
    # Operating expenses = 500
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("500.00"),
        category="FUEL",
        description="CNG",
        transaction_date=date_str,
        idempotency_key="ST_TXN_2"
    )
    # Owner payment = 450
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("450.00"),
        category="OWNER_RENT",
        description="Paid owner via UPI",
        transaction_date=date_str,
        idempotency_key="ST_TXN_3"
    )

    # 1. Create settlement v1 with previous balance of ₹100 (Example A)
    s1 = settle_svc.create_settlement(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        settlement_date=date_str,
        shift_id="DEFAULT",
        previous_balance=Decimal("100.00"),
        idempotency_key="SETTLE_KEY_1"
    )

    assert s1["version"] == 1
    assert s1["previous_balance"] == "100.00"
    assert s1["expected_rent"] == "350.00"
    assert s1["gross_income"] == "2000.00"
    assert s1["operating_expenses"] == "500.00"
    assert s1["operating_profit"] == "1500.00"
    assert s1["owner_payments"] == "450.00"
    assert s1["total_obligation"] == "450.00"
    assert s1["remaining_balance"] == "0.00"
    assert s1["driver_take_home"] == "1050.00"
    assert s1["settlement_status"] == "SETTLED"

    # 2. Attempting to create duplicate v1 settlement must fail
    with pytest.raises(ValueError) as exc:
        settle_svc.create_settlement(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            settlement_date=date_str,
            shift_id="DEFAULT",
            previous_balance=Decimal("100.00"),
            idempotency_key="SETTLE_KEY_DUP"
        )
    assert "Settlement already exists" in str(exc.value)


def test_settlement_recalculation_versioning(db):
    audit = AuditService(db)
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo, audit_service=audit)
    settle_svc = SettlementService(db=db, repo=repo, audit_service=audit)

    driver_id = "DRV_SETTLE_2"
    vehicle_id = "KA03EF9012"
    date_str = "2026-11-08"

    settle_svc.get_or_create_vehicle(vehicle_id, driver_id, default_rent=Decimal("350.00"))

    # Initial ledger records
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.INCOME,
        amount=Decimal("2000.00"),
        category="FARE",
        description="Fares",
        transaction_date=date_str,
        idempotency_key="RE_TXN_1"
    )
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("500.00"),
        category="FUEL",
        description="Fuel",
        transaction_date=date_str,
        idempotency_key="RE_TXN_2"
    )
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("250.00"),
        category="OWNER_RENT",
        description="Partial rent",
        transaction_date=date_str,
        idempotency_key="RE_TXN_3"
    )

    # Version 1 Settlement (Example B: remaining balance = 200, PARTIALLY_SETTLED)
    s1 = settle_svc.create_settlement(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        settlement_date=date_str,
        previous_balance=Decimal("100.00"),
        idempotency_key="RE_KEY_1"
    )
    assert s1["version"] == 1
    assert s1["remaining_balance"] == "200.00"
    assert s1["settlement_status"] == "PARTIALLY_SETTLED"

    # Driver pays additional ₹200 to owner later that night
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("200.00"),
        category="OWNER_RENT",
        description="Remaining rent balance paid",
        transaction_date=date_str,
        idempotency_key="RE_TXN_4"
    )

    # Recalculate settlement -> Creates Version 2!
    s2 = settle_svc.recalculate_settlement(
        settlement_id=s1["settlement_id"],
        driver_id=driver_id,
        reason="Driver cleared remaining balance with second UPI payment",
        idempotency_key="RE_KEY_2"
    )

    assert s2["version"] == 2
    assert s2["supersedes_settlement_id"] == s1["settlement_id"]
    assert s2["recalculation_reason"] == "Driver cleared remaining balance with second UPI payment"
    assert s2["owner_payments"] == "450.00"  # 250 + 200
    assert s2["remaining_balance"] == "0.00"  # Now fully settled!
    assert s2["settlement_status"] == "SETTLED"

    # VERIFY VERSION 1 RECORD IS COMPLETELY PRESERVED IN DATABASE
    s1_history = settle_svc.get_settlement(s1["settlement_id"], driver_id=driver_id)
    assert s1_history is not None
    assert s1_history["version"] == 1
    assert s1_history["remaining_balance"] == "200.00"
    assert s1_history["settlement_status"] == "PARTIALLY_SETTLED"
