"""
Unit tests for Financial Domain Models and Pydantic Validators.
Tests signed amount invariants, positive amount requirements,
float rejection, and domain constraints.
"""

import pytest
from decimal import Decimal
from app.models.financial import (
    FinancialTransaction,
    TransactionType,
    Vehicle,
    Settlement,
    PendingAction,
    PendingActionType,
    PendingActionStatus,
    SettlementStatus,
    quantize_money,
    format_money
)


def test_quantize_and_format_money():
    # Valid conversions
    assert quantize_money("123.456") == Decimal("123.46")  # ROUND_HALF_UP
    assert quantize_money(100) == Decimal("100.00")
    assert quantize_money(Decimal("50.5")) == Decimal("50.50")
    assert format_money(Decimal("1234.5")) == "1234.50"

    # Float contamination must be strictly rejected
    with pytest.raises(TypeError) as exc:
        quantize_money(123.45)
    assert "Floating-point monetary amount" in str(exc.value)

    # Invalid / non-finite
    with pytest.raises(ValueError):
        quantize_money("not-a-number")
    with pytest.raises(ValueError):
        quantize_money(Decimal("Infinity"))


def test_financial_transaction_signed_amounts():
    # 1. Income: signed_amount must equal +amount
    txn_inc = FinancialTransaction(
        transaction_id="TXN_1",
        driver_id="DRV_1",
        vehicle_id="VEH_1",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("500.00"),
        signed_amount=Decimal("500.00"),
        category="FARE",
        created_by="DRV_1",
        idempotency_key="KEY_1"
    )
    assert txn_inc.amount == Decimal("500.00")
    assert txn_inc.signed_amount == Decimal("500.00")

    # Income with mismatching signed amount must fail
    with pytest.raises(ValueError) as exc:
        FinancialTransaction(
            transaction_id="TXN_1",
            driver_id="DRV_1",
            vehicle_id="VEH_1",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("500.00"),
            signed_amount=Decimal("-500.00"),
            category="FARE",
            created_by="DRV_1",
            idempotency_key="KEY_1"
        )
    assert "INCOME signed_amount must equal +amount" in str(exc.value)

    # 2. Expense: signed_amount must equal -amount
    txn_exp = FinancialTransaction(
        transaction_id="TXN_2",
        driver_id="DRV_1",
        vehicle_id="VEH_1",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("300.00"),
        signed_amount=Decimal("-300.00"),
        category="FUEL",
        created_by="DRV_1",
        idempotency_key="KEY_2"
    )
    assert txn_exp.signed_amount == Decimal("-300.00")

    # 3. Owner Payment: signed_amount must equal -amount
    txn_owner = FinancialTransaction(
        transaction_id="TXN_3",
        driver_id="DRV_1",
        vehicle_id="VEH_1",
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("450.00"),
        signed_amount=Decimal("-450.00"),
        category="OWNER_RENT",
        created_by="DRV_1",
        idempotency_key="KEY_3"
    )
    assert txn_owner.signed_amount == Decimal("-450.00")

    # 4. Income Reversal: signed_amount must equal -amount, must have reference_id
    txn_rev = FinancialTransaction(
        transaction_id="TXN_4",
        driver_id="DRV_1",
        vehicle_id="VEH_1",
        transaction_type=TransactionType.INCOME_REVERSAL,
        amount=Decimal("500.00"),
        signed_amount=Decimal("-500.00"),
        category="FARE",
        created_by="DRV_1",
        idempotency_key="KEY_4",
        reference_id="TXN_1"
    )
    assert txn_rev.signed_amount == Decimal("-500.00")

    # Missing reference_id on reversal must raise
    with pytest.raises(ValueError) as exc:
        FinancialTransaction(
            transaction_id="TXN_5",
            driver_id="DRV_1",
            vehicle_id="VEH_1",
            transaction_type=TransactionType.INCOME_REVERSAL,
            amount=Decimal("500.00"),
            signed_amount=Decimal("-500.00"),
            category="FARE",
            created_by="DRV_1",
            idempotency_key="KEY_5"
        )
    assert "must include a reference_id" in str(exc.value)


def test_negative_and_zero_amount_rejection():
    # Negative amount rejected
    with pytest.raises(ValueError):
        FinancialTransaction(
            transaction_id="TXN_ERR",
            driver_id="DRV_1",
            vehicle_id="VEH_1",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("-100.00"),
            signed_amount=Decimal("-100.00"),
            category="FARE",
            created_by="DRV_1",
            idempotency_key="KEY_ERR"
        )

    # Zero amount rejected
    with pytest.raises(ValueError):
        FinancialTransaction(
            transaction_id="TXN_ZERO",
            driver_id="DRV_1",
            vehicle_id="VEH_1",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("0.00"),
            signed_amount=Decimal("0.00"),
            category="FARE",
            created_by="DRV_1",
            idempotency_key="KEY_ZERO"
        )


def test_vehicle_and_settlement_models():
    veh = Vehicle(
        vehicle_id="KA01AB1234",
        owner_id="OWN_1",
        registration_number="KA01AB1234",
        rent_amount=Decimal("350.00")
    )
    assert veh.rent_amount == Decimal("350.00")

    settle = Settlement(
        settlement_id="SETTLE_1",
        driver_id="DRV_1",
        vehicle_id="KA01AB1234",
        settlement_date="2026-11-08",
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("500.00"),
        operating_profit=Decimal("1500.00"),
        owner_payments=Decimal("450.00"),
        total_obligation=Decimal("450.00"),
        remaining_balance=Decimal("0.00"),
        driver_take_home=Decimal("1050.00"),
        settlement_status=SettlementStatus.SETTLED
    )
    assert settle.settlement_status == SettlementStatus.SETTLED
    assert settle.driver_take_home == Decimal("1050.00")
