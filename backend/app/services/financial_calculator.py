"""
Deterministic Financial Calculation Engine for T2T DRIVE.
Executes pure Python Decimal arithmetic for transactions, metrics,
period summaries, and owner-driver settlements.
Completely isolated from LLMs and external networks.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Tuple
from app.models.financial import (
    TransactionType,
    SettlementStatus,
    quantize_money,
    format_money,
    TWO_PLACES
)


class FinancialCalculator:
    """
    Stateless, deterministic calculation engine for all financial metrics.
    Guarantees zero floating-point arithmetic and consistent INR 2-decimal precision.
    """

    @staticmethod
    def calculate_signed_amount(
        transaction_type: TransactionType,
        amount: Decimal,
        adjustment_delta: Decimal = Decimal("0.00")
    ) -> Decimal:
        """
        Determines the signed financial impact of a transaction.
        """
        amt = quantize_money(amount)
        if amt <= Decimal("0.00") and transaction_type not in (
            TransactionType.INCOME_ADJUSTMENT,
            TransactionType.EXPENSE_ADJUSTMENT
        ):
            raise ValueError(f"Amount must be strictly positive (> 0), got: {amt}")

        if transaction_type == TransactionType.INCOME:
            return amt
        elif transaction_type in (TransactionType.EXPENSE, TransactionType.OWNER_PAYMENT):
            return -amt
        elif transaction_type == TransactionType.INCOME_REVERSAL:
            return -amt
        elif transaction_type in (TransactionType.EXPENSE_REVERSAL, TransactionType.OWNER_PAYMENT_REVERSAL):
            return amt
        elif transaction_type in (TransactionType.INCOME_ADJUSTMENT, TransactionType.EXPENSE_ADJUSTMENT):
            return quantize_money(adjustment_delta)
        else:
            raise ValueError(f"Unsupported transaction type: {transaction_type}")

    @classmethod
    def calculate_metrics(cls, transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Computes financial summary metrics from a list of transactions.
        Accounts for reversals and adjustments via their signed_amount.
        """
        income_signed_sum = Decimal("0.00")
        expense_signed_sum = Decimal("0.00")
        owner_payment_signed_sum = Decimal("0.00")

        category_expenses: Dict[str, Decimal] = {}
        category_income: Dict[str, Decimal] = {}

        for txn in transactions:
            raw_s_amt = txn.get("signed_amount", Decimal("0.00"))
            s_amt = quantize_money(raw_s_amt)
            tt = txn.get("transaction_type")
            cat = str(txn.get("category", "OTHER")).upper()

            if tt in (TransactionType.INCOME, TransactionType.INCOME_REVERSAL, TransactionType.INCOME_ADJUSTMENT):
                income_signed_sum += s_amt
                category_income[cat] = category_income.get(cat, Decimal("0.00")) + s_amt

            elif tt in (TransactionType.EXPENSE, TransactionType.EXPENSE_REVERSAL, TransactionType.EXPENSE_ADJUSTMENT):
                expense_signed_sum += s_amt
                # For category expenses, we track absolute cost, so negative signed amounts add to expense
                category_expenses[cat] = category_expenses.get(cat, Decimal("0.00")) - s_amt

            elif tt in (TransactionType.OWNER_PAYMENT, TransactionType.OWNER_PAYMENT_REVERSAL):
                owner_payment_signed_sum += s_amt

        # Gross Income: Net positive income
        gross_income = max(income_signed_sum, Decimal("0.00"))
        # Operating Expenses: Absolute value of net expense deductions
        operating_expenses = max(-expense_signed_sum, Decimal("0.00"))
        # Operating Profit: Income minus operating expenses
        operating_profit = gross_income - operating_expenses
        # Owner Payments: Absolute value of net owner payments
        owner_payments = max(-owner_payment_signed_sum, Decimal("0.00"))
        # Driver Take-Home: Cash remaining after operating costs AND owner payments
        driver_take_home = operating_profit - owner_payments
        # Net Cash Retained: Same as driver take-home in single-driver context
        net_cash_retained = gross_income - operating_expenses - owner_payments

        # Clean up category dicts to format strings
        formatted_category_expenses = {
            cat: format_money(max(amt, Decimal("0.00")))
            for cat, amt in category_expenses.items()
        }
        formatted_category_income = {
            cat: format_money(max(amt, Decimal("0.00")))
            for cat, amt in category_income.items()
        }

        return {
            "gross_income": format_money(gross_income),
            "operating_expenses": format_money(operating_expenses),
            "operating_profit": format_money(operating_profit),
            "owner_payments": format_money(owner_payments),
            "driver_take_home": format_money(driver_take_home),
            "net_cash_retained": format_money(net_cash_retained),
            "transaction_count": len(transactions),
            "category_expenses": formatted_category_expenses,
            "category_income": formatted_category_income,
            # Raw Decimals for internal chaining
            "_raw": {
                "gross_income": gross_income,
                "operating_expenses": operating_expenses,
                "operating_profit": operating_profit,
                "owner_payments": owner_payments,
                "driver_take_home": driver_take_home,
                "net_cash_retained": net_cash_retained,
            }
        }

    @staticmethod
    def calculate_settlement(
        previous_balance: Decimal,
        expected_rent: Decimal,
        gross_income: Decimal,
        operating_expenses: Decimal,
        owner_payments: Decimal
    ) -> Dict[str, Any]:
        """
        Executes the owner-driver settlement formulas:
        C_operating = I_gross - E_ops
        O_total = R_expected + B_prev
        B_rem = O_total - P_actual
        W_take_home = C_operating - P_actual

        Status:
        - SETTLED when B_rem == 0
        - PARTIALLY_SETTLED when B_rem > 0
        - OVERPAID when B_rem < 0
        """
        b_prev = quantize_money(previous_balance)  # May be positive (debt), zero (settled), or negative (credit)
        r_exp = quantize_money(expected_rent)
        i_gross = quantize_money(gross_income)
        e_ops = quantize_money(operating_expenses)
        p_actual = quantize_money(owner_payments)

        # Enforce non-negative constraint on operational figures
        if r_exp < Decimal("0.00"):
            raise ValueError(f"Expected rent must be non-negative (>= 0), got: {r_exp}")
        if i_gross < Decimal("0.00"):
            raise ValueError(f"Gross income must be non-negative (>= 0), got: {i_gross}")
        if e_ops < Decimal("0.00"):
            raise ValueError(f"Operating expenses must be non-negative (>= 0), got: {e_ops}")
        if p_actual < Decimal("0.00"):
            raise ValueError(f"Owner payments must be non-negative (>= 0), got: {p_actual}")

        # 1. Operating Profit
        c_operating = i_gross - e_ops

        # 2. Total Owner Obligation (Rent + Previous Outstanding Balance / Credit)
        o_total = r_exp + b_prev

        # 3. Remaining Balance after actual owner payments (Positive = debt, Negative = credit)
        b_rem = o_total - p_actual

        # 4. Driver Take-Home Cash
        w_take_home = c_operating - p_actual

        # 5. Settlement Status determination
        if b_rem == Decimal("0.00"):
            status = SettlementStatus.SETTLED
        elif b_rem > Decimal("0.00"):
            status = SettlementStatus.PARTIALLY_SETTLED
        else:
            status = SettlementStatus.OVERPAID

        return {
            "previous_balance": format_money(b_prev),
            "expected_rent": format_money(r_exp),
            "gross_income": format_money(i_gross),
            "operating_expenses": format_money(e_ops),
            "operating_profit": format_money(c_operating),
            "owner_payments": format_money(p_actual),
            "total_obligation": format_money(o_total),
            "remaining_balance": format_money(b_rem),
            "driver_take_home": format_money(w_take_home),
            "settlement_status": status.value,
            "_raw": {
                "previous_balance": b_prev,
                "expected_rent": r_exp,
                "gross_income": i_gross,
                "operating_expenses": e_ops,
                "operating_profit": c_operating,
                "owner_payments": p_actual,
                "total_obligation": o_total,
                "remaining_balance": b_rem,
                "driver_take_home": w_take_home,
                "settlement_status": status,
            }
        }
