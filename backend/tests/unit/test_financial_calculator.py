"""
Unit tests for Deterministic Financial Calculation Engine.
Verifies all mandatory calculation examples from the specification.
"""

from decimal import Decimal
from app.models.financial import TransactionType, SettlementStatus
from app.services.financial_calculator import FinancialCalculator


def test_core_financial_calculation_example():
    """
    Specification Example:
    Income: ₹2,000
    Fuel expense: ₹300
    Food expense: ₹100
    Owner payment: ₹450

    Expected results:
    Gross income = ₹2,000
    Operating expenses = ₹400
    Operating profit = ₹1,600
    Owner payments = ₹450
    Driver take-home = ₹1,150
    """
    txns = [
        {
            "transaction_type": TransactionType.INCOME,
            "signed_amount": Decimal("2000.00"),
            "category": "FARE"
        },
        {
            "transaction_type": TransactionType.EXPENSE,
            "signed_amount": Decimal("-300.00"),
            "category": "FUEL"
        },
        {
            "transaction_type": TransactionType.EXPENSE,
            "signed_amount": Decimal("-100.00"),
            "category": "FOOD"
        },
        {
            "transaction_type": TransactionType.OWNER_PAYMENT,
            "signed_amount": Decimal("-450.00"),
            "category": "OWNER_RENT"
        }
    ]

    metrics = FinancialCalculator.calculate_metrics(txns)

    assert metrics["gross_income"] == "2000.00"
    assert metrics["operating_expenses"] == "400.00"
    assert metrics["operating_profit"] == "1600.00"
    assert metrics["owner_payments"] == "450.00"
    assert metrics["driver_take_home"] == "1150.00"
    assert metrics["net_cash_retained"] == "1150.00"
    assert metrics["transaction_count"] == 4
    assert metrics["category_expenses"]["FUEL"] == "300.00"
    assert metrics["category_expenses"]["FOOD"] == "100.00"


def test_settlement_example_a():
    """
    Specification Example A:
    Previous balance = ₹100
    Expected rent = ₹350
    Gross income = ₹2,000
    Operating expenses = ₹500
    Owner payment = ₹450

    Expected result:
    Operating profit = ₹1,500
    Total obligation = ₹450
    Remaining balance = ₹0
    Driver take-home = ₹1,050
    Status = SETTLED
    """
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("100.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("500.00"),
        owner_payments=Decimal("450.00")
    )

    assert res["operating_profit"] == "1500.00"
    assert res["total_obligation"] == "450.00"
    assert res["remaining_balance"] == "0.00"
    assert res["driver_take_home"] == "1050.00"
    assert res["settlement_status"] == "SETTLED"


def test_settlement_example_b():
    """
    Specification Example B:
    Previous balance = ₹100
    Expected rent = ₹350
    Gross income = ₹2,000
    Operating expenses = ₹500
    Owner payment = ₹250

    Expected result:
    Operating profit = ₹1,500
    Total obligation = ₹450
    Remaining balance = ₹200
    Driver take-home = ₹1,250
    Status = PARTIALLY_SETTLED
    """
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("100.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("500.00"),
        owner_payments=Decimal("250.00")
    )

    assert res["operating_profit"] == "1500.00"
    assert res["total_obligation"] == "450.00"
    assert res["remaining_balance"] == "200.00"
    assert res["driver_take_home"] == "1250.00"
    assert res["settlement_status"] == "PARTIALLY_SETTLED"


def test_settlement_overpaid():
    """
    Driver pays ₹400 on an expected ₹350 rent with 0 previous balance.
    Result: Remaining balance = -₹50 (credit advance), status = OVERPAID.
    """
    res = FinancialCalculator.calculate_settlement(
        previous_balance=Decimal("0.00"),
        expected_rent=Decimal("350.00"),
        gross_income=Decimal("2000.00"),
        operating_expenses=Decimal("500.00"),
        owner_payments=Decimal("400.00")
    )

    assert res["total_obligation"] == "350.00"
    assert res["remaining_balance"] == "-50.00"
    assert res["settlement_status"] == "OVERPAID"
    assert res["driver_take_home"] == "1100.00"


def test_metrics_with_reversals_and_adjustments():
    """
    Tests that reversals cancel out original amounts and adjustments apply net changes.
    """
    txns = [
        # Original Income 500, then reversed
        {"transaction_type": TransactionType.INCOME, "signed_amount": Decimal("500.00"), "category": "FARE"},
        {"transaction_type": TransactionType.INCOME_REVERSAL, "signed_amount": Decimal("-500.00"), "category": "FARE"},
        # New valid income
        {"transaction_type": TransactionType.INCOME, "signed_amount": Decimal("800.00"), "category": "FARE"},
        # Original expense 500, reversed, replaced with 450
        {"transaction_type": TransactionType.EXPENSE, "signed_amount": Decimal("-500.00"), "category": "FUEL"},
        {"transaction_type": TransactionType.EXPENSE_REVERSAL, "signed_amount": Decimal("500.00"), "category": "FUEL"},
        {"transaction_type": TransactionType.EXPENSE, "signed_amount": Decimal("-450.00"), "category": "FUEL"}
    ]

    metrics = FinancialCalculator.calculate_metrics(txns)

    assert metrics["gross_income"] == "800.00"
    assert metrics["operating_expenses"] == "450.00"
    assert metrics["operating_profit"] == "350.00"
    assert metrics["category_expenses"]["FUEL"] == "450.00"
    assert metrics["category_income"]["FARE"] == "800.00"
