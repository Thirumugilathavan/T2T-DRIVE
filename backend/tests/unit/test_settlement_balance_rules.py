"""
Regression tests for Settlement Balance Rules (Critical Correction A).
Verifies:
1. Positive previous balance (existing debt).
2. Negative previous balance (advance credit).
3. Zero previous balance.
4. Exact settlement (SETTLED).
5. Partial settlement (PARTIALLY_SETTLED).
6. Overpayment resulting in negative remaining balance (OVERPAID).
7. Negative balance carried into the next settlement.
8. Reconciliation after a reversal or adjustment.
9. Strict rejection of negative operating figures (expected rent, income, expenses, owner payments).
"""

import pytest
from decimal import Decimal
from app.models.financial import TransactionType, Settlement, SettlementStatus
from app.services.financial_calculator import FinancialCalculator
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.settlement_service import SettlementService


def test_positive_previous_balance_debt():
    """Driver carried forward ₹150 debt. Rent ₹350. Total obligation = ₹500."""
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("150.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("400.00"),
        owner_payments=Decimal("350.00")
    )
    assert res["total_obligation"] == "500.00"
    assert res["remaining_balance"] == "150.00"
    assert res["settlement_status"] == "PARTIALLY_SETTLED"
    assert res["driver_take_home"] == "1250.00"  # 1600 - 350


def test_negative_previous_balance_advance_credit():
    """Driver had ₹100 advance credit. Rent ₹350. Total obligation = ₹250."""
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("-100.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("400.00"),
        owner_payments=Decimal("250.00")
    )
    assert res["total_obligation"] == "250.00"  # 350 - 100
    assert res["remaining_balance"] == "0.00"
    assert res["settlement_status"] == "SETTLED"
    assert res["driver_take_home"] == "1350.00"  # 1600 - 250


def test_zero_previous_balance_exact_settlement():
    """Zero balance, pays exact rent of ₹350 -> SETTLED."""
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("0.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("1800.00"),
        operating_expenses=Decimal("300.00"),
        owner_payments=Decimal("350.00")
    )
    assert res["total_obligation"] == "350.00"
    assert res["remaining_balance"] == "0.00"
    assert res["settlement_status"] == "SETTLED"


def test_overpayment_creates_negative_remaining_balance():
    """Driver owes ₹350 rent, pays ₹500 -> remaining balance = -₹150 (OVERPAID)."""
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("0.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2500.00"),
        operating_expenses=Decimal("500.00"),
        owner_payments=Decimal("500.00")
    )
    assert res["total_obligation"] == "350.00"
    assert res["remaining_balance"] == "-150.00"
    assert res["settlement_status"] == "OVERPAID"


def test_rejection_of_negative_operating_figures():
    """Operational amounts cannot be negative."""
    # Negative expected rent
    with pytest.raises(ValueError) as exc1:
        FinancialCalculator.calculate_settlement(
            previous_balance=Decimal("0.00"),
            expected_rent=Decimal("-100.00"),
            gross_income=Decimal("1000.00"),
            operating_expenses=Decimal("200.00"),
            owner_payments=Decimal("350.00")
        )
    assert "Expected rent must be non-negative" in str(exc1.value)

    # Negative income
    with pytest.raises(ValueError) as exc2:
        FinancialCalculator.calculate_settlement(
            previous_balance=Decimal("0.00"),
            expected_rent=Decimal("350.00"),
            gross_income=Decimal("-100.00"),
            operating_expenses=Decimal("200.00"),
            owner_payments=Decimal("350.00")
        )
    assert "Gross income must be non-negative" in str(exc2.value)

    # Negative expenses
    with pytest.raises(ValueError) as exc3:
        FinancialCalculator.calculate_settlement(
            previous_balance=Decimal("0.00"),
            expected_rent=Decimal("350.00"),
            gross_income=Decimal("1000.00"),
            operating_expenses=Decimal("-200.00"),
            owner_payments=Decimal("350.00")
        )
    assert "Operating expenses must be non-negative" in str(exc3.value)


def test_advance_credit_carried_forward_into_next_day(db):
    """
    Day 1: Driver overpays, creating advance credit (remaining_balance = -₹100).
    Day 2: Settlement automatically carries forward -₹100 as previous_balance!
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    settle_svc = SettlementService(db=db, repo=repo)

    driver_id = "DRV_ADV_CREDIT"
    vehicle_id = "KA05MN1234"
    settle_svc.get_or_create_vehicle(vehicle_id, driver_id, default_rent=Decimal("350.00"))

    # Day 1: 2026-11-01 -> Rent ₹350, pays ₹450 -> Overpaid by ₹100
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("450.00"),
        category="OWNER_RENT",
        description="Day 1 advance payment",
        transaction_date="2026-11-01",
        idempotency_key="D1_PAY"
    )

    s1 = settle_svc.create_settlement(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        settlement_date="2026-11-01",
        idempotency_key="D1_SETTLE"
    )
    assert s1["remaining_balance"] == "-100.00"
    assert s1["settlement_status"] == "OVERPAID"

    # Day 2: 2026-11-02 -> Rent ₹350.
    # Driver pays only ₹250 because they have ₹100 credit.
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("250.00"),
        category="OWNER_RENT",
        description="Day 2 partial payment adjusting credit",
        transaction_date="2026-11-02",
        idempotency_key="D2_PAY"
    )

    s2 = settle_svc.create_settlement(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        settlement_date="2026-11-02",
        idempotency_key="D2_SETTLE"
    )

    # Day 2 must automatically carry forward previous_balance = -₹100!
    assert s2["previous_balance"] == "-100.00"
    assert s2["total_obligation"] == "250.00"  # 350 - 100
    assert s2["owner_payments"] == "250.00"
    assert s2["remaining_balance"] == "0.00"  # Fully settled!
    assert s2["settlement_status"] == "SETTLED"


def test_settlement_recalculation_after_expense_reversal(db):
    """
    Verifies that recalculating a settlement after an expense reversal
    updates operating profit and take-home cash while preserving version history.
    """
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    settle_svc = SettlementService(db=db, repo=repo)

    driver_id = "DRV_RECALC_TEST"
    vehicle_id = "KA05MN5678"
    date_str = "2026-11-08"

    settle_svc.get_or_create_vehicle(vehicle_id, driver_id, default_rent=Decimal("350.00"))

    # Initial: Income 2000, Expense 500, Payment 350
    t_inc = ledger.record_transaction(driver_id, vehicle_id, TransactionType.INCOME, Decimal("2000.00"), "FARE", "Trip", "INC_1", transaction_date=date_str)
    t_exp = ledger.record_transaction(driver_id, vehicle_id, TransactionType.EXPENSE, Decimal("500.00"), "FUEL", "Fuel", "EXP_1", transaction_date=date_str)
    t_pay = ledger.record_transaction(driver_id, vehicle_id, TransactionType.OWNER_PAYMENT, Decimal("350.00"), "OWNER_RENT", "Rent", "PAY_1", transaction_date=date_str)

    # Settlement v1: Operating profit = 1500, take-home = 1150
    s1 = settle_svc.create_settlement(driver_id, vehicle_id, date_str, idempotency_key="S_V1")
    assert s1["version"] == 1
    assert s1["operating_profit"] == "1500.00"
    assert s1["driver_take_home"] == "1150.00"

    # Later: Driver realizes fuel was charged erroneously and reverses the ₹500 expense
    ledger.create_reversal(t_exp["transaction_id"], driver_id, "Erroneous fuel charge refunded", "REV_FUEL")

    # Recalculate settlement -> Version 2
    s2 = settle_svc.recalculate_settlement(
        settlement_id=s1["settlement_id"],
        driver_id=driver_id,
        reason="Fuel expense reversed after refund",
        idempotency_key="S_V2"
    )

    assert s2["version"] == 2
    assert s2["operating_expenses"] == "0.00"  # 500 - 500
    assert s2["operating_profit"] == "2000.00"  # 2000 - 0
    assert s2["driver_take_home"] == "1650.00"  # 2000 - 350
    assert s2["supersedes_settlement_id"] == s1["settlement_id"]

    # History v1 is untouched
    s1_check = settle_svc.get_settlement(s1["settlement_id"], driver_id)
    assert s1_check["version"] == 1
    assert s1_check["operating_profit"] == "1500.00"
