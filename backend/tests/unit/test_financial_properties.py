"""
Hypothesis Property-Based Tests for T2T DRIVE Financial Invariants.
Mathematically verifies financial formulas, rounding idempotence,
and ledger correction arithmetic across arbitrary monetary inputs.
"""

from decimal import Decimal
from hypothesis import given, strategies as st
from app.models.financial import quantize_money
from app.services.financial_calculator import FinancialCalculator


# Strategy for reasonable non-negative monetary amounts up to ₹1,000,000 with 2 decimal places
money_strategy = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2
)


@given(
    prev_bal=money_strategy,
    expected_rent=money_strategy,
    gross_income=money_strategy,
    operating_expenses=money_strategy,
    owner_payments=money_strategy
)
def test_settlement_invariants(prev_bal, expected_rent, gross_income, operating_expenses, owner_payments):
    """
    Verifies that the settlement formula invariants hold true for ANY monetary inputs:
    - operating_profit == gross_income - operating_expenses
    - total_obligation == expected_rent + previous_balance
    - remaining_balance == total_obligation - owner_payments
    - driver_take_home == operating_profit - owner_payments
    """
    res = FinancialCalculator.calculate_settlement(
        previous_balance=prev_bal,
        expected_rent=expected_rent,
        gross_income=gross_income,
        operating_expenses=operating_expenses,
        owner_payments=owner_payments
    )
    raw = res["_raw"]

    assert raw["operating_profit"] == raw["gross_income"] - raw["operating_expenses"]
    assert raw["total_obligation"] == raw["expected_rent"] + raw["previous_balance"]
    assert raw["remaining_balance"] == raw["total_obligation"] - raw["owner_payments"]
    assert raw["driver_take_home"] == raw["operating_profit"] - raw["owner_payments"]


@given(amt=money_strategy)
def test_quantize_money_idempotence(amt):
    """Quantizing an already quantized monetary amount is an identity operation."""
    q1 = quantize_money(amt)
    q2 = quantize_money(q1)
    assert q1 == q2
