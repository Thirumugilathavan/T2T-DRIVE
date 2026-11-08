"""
Pydantic v2 Domain Models and Enums for T2T DRIVE Financial Engine.
Enforces strict monetary types (Decimal), signed amount invariants,
and domain validation across transactions, settlements, vehicles, and pending actions.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Optional, List, Dict, Any
import datetime
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from app.utils.dates import now_utc, today_ist


# ============================================================================
# ENUMS
# ============================================================================

class TransactionType(str, Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    OWNER_PAYMENT = "OWNER_PAYMENT"
    INCOME_REVERSAL = "INCOME_REVERSAL"
    EXPENSE_REVERSAL = "EXPENSE_REVERSAL"
    INCOME_ADJUSTMENT = "INCOME_ADJUSTMENT"
    EXPENSE_ADJUSTMENT = "EXPENSE_ADJUSTMENT"
    OWNER_PAYMENT_REVERSAL = "OWNER_PAYMENT_REVERSAL"


class IncomeCategory(str, Enum):
    FARE = "FARE"
    TIP = "TIP"
    OTHER_INCOME = "OTHER_INCOME"


class ExpenseCategory(str, Enum):
    FUEL = "FUEL"
    FOOD = "FOOD"
    MAINTENANCE = "MAINTENANCE"
    PARKING = "PARKING"
    TOLL = "TOLL"
    VEHICLE_CLEANING = "VEHICLE_CLEANING"
    MOBILE_RECHARGE = "MOBILE_RECHARGE"
    RENT = "RENT"
    OTHER_EXPENSE = "OTHER_EXPENSE"


class OwnerPaymentCategory(str, Enum):
    OWNER_RENT = "OWNER_RENT"
    OWNER_DUES = "OWNER_DUES"
    OWNER_PAYMENT = "OWNER_PAYMENT"


class RentFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    PER_SHIFT = "PER_SHIFT"


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    OVERPAID = "OVERPAID"


class PendingActionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PendingActionType(str, Enum):
    ADD_INCOME = "ADD_INCOME"
    ADD_EXPENSE = "ADD_EXPENSE"
    ADD_OWNER_PAYMENT = "ADD_OWNER_PAYMENT"
    CREATE_ADJUSTMENT = "CREATE_ADJUSTMENT"
    CREATE_REVERSAL = "CREATE_REVERSAL"
    CREATE_SETTLEMENT = "CREATE_SETTLEMENT"
    RECALCULATE_SETTLEMENT = "RECALCULATE_SETTLEMENT"


# ============================================================================
# MONETARY HELPER FUNCTIONS
# ============================================================================

TWO_PLACES = Decimal("0.01")

def quantize_money(amount: Any) -> Decimal:
    """
    Converts and quantizes an amount into strict INR Decimal (2 decimal places).
    Rejects NaN, Infinity, and floats to avoid precision contamination.
    """
    if isinstance(amount, float):
        raise TypeError(
            f"Floating-point monetary amount ({amount}) is strictly prohibited. "
            "Pass string, int, or Decimal."
        )
    try:
        dec = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as err:
        raise ValueError(f"Invalid monetary value: {amount}") from err

    if not dec.is_finite():
        raise ValueError(f"Monetary value must be finite: {amount}")

    # Quantize to 2 decimal places using standard financial rounding
    return dec.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    """Formats Decimal to standard 2-decimal string (e.g. '1250.00')."""
    return f"{quantize_money(amount):.2f}"


# ============================================================================
# MODELS
# ============================================================================

class FinancialTransaction(BaseModel):
    """
    Immutable representation of a financial ledger entry.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    transaction_id: str = Field(..., description="Unique transaction ID (e.g. TXN_...)")
    driver_id: str = Field(..., description="Driver identifier")
    vehicle_id: str = Field(..., description="Vehicle registration or ID")
    transaction_type: TransactionType = Field(..., description="Type of transaction")
    amount: Decimal = Field(..., description="Absolute positive transaction value")
    signed_amount: Decimal = Field(..., description="Net signed financial effect on cash balance")
    category: str = Field(..., description="Category (FARE, FUEL, etc.)")
    description: str = Field(default="", description="Human-readable description or voice note")
    transaction_date: str = Field(default_factory=today_ist, description="Calendar date YYYY-MM-DD (IST)")
    created_at: datetime.datetime = Field(default_factory=now_utc, description="UTC creation timestamp")
    created_by: str = Field(..., description="Actor who created record")
    idempotency_key: str = Field(..., description="Unique client idempotency key")
    source: str = Field(default="MANUAL", description="Source channel: VOICE, MANUAL, SYSTEM")
    reference_id: Optional[str] = Field(default=None, description="Original transaction_id for reversals/adjustments")
    status: str = Field(default="COMPLETED", description="Ledger status (always COMPLETED in append-only ledger)")

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec <= Decimal("0"):
            raise ValueError(f"Transaction amount must be strictly positive (> 0), got: {dec}")
        return dec

    @field_validator("signed_amount", mode="before")
    @classmethod
    def validate_signed_amount(cls, v: Any) -> Decimal:
        return quantize_money(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        clean = v.strip().upper()
        if not clean:
            raise ValueError("Category cannot be empty.")
        return clean

    @model_validator(mode="after")
    def validate_signed_amount_rules(self) -> "FinancialTransaction":
        """
        Enforces the signed amount mathematical invariant based on transaction type.
        """
        amt = self.amount
        s_amt = self.signed_amount
        tt = self.transaction_type

        if tt == TransactionType.INCOME:
            if s_amt != amt:
                raise ValueError(f"INCOME signed_amount must equal +amount (+{amt}), got: {s_amt}")

        elif tt in (TransactionType.EXPENSE, TransactionType.OWNER_PAYMENT):
            if s_amt != -amt:
                raise ValueError(f"{tt.value} signed_amount must equal -amount (-{amt}), got: {s_amt}")

        elif tt == TransactionType.INCOME_REVERSAL:
            if s_amt != -amt:
                raise ValueError(f"INCOME_REVERSAL signed_amount must equal -amount (-{amt}), got: {s_amt}")
            if not self.reference_id:
                raise ValueError("INCOME_REVERSAL must include a reference_id to the original transaction.")

        elif tt in (TransactionType.EXPENSE_REVERSAL, TransactionType.OWNER_PAYMENT_REVERSAL):
            if s_amt != amt:
                raise ValueError(f"{tt.value} signed_amount must equal +amount (+{amt}), got: {s_amt}")
            if not self.reference_id:
                raise ValueError(f"{tt.value} must include a reference_id to the original transaction.")

        elif tt in (TransactionType.INCOME_ADJUSTMENT, TransactionType.EXPENSE_ADJUSTMENT):
            if not self.reference_id:
                raise ValueError(f"{tt.value} must include a reference_id to the original transaction.")
            # Adjustments can be positive or negative depending on correction direction

        return self


class Vehicle(BaseModel):
    """
    Vehicle model representing registered vehicle and rental terms.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vehicle_id: str
    owner_id: str
    vehicle_type: str = "AUTO_RICKSHAW"  # AUTO_RICKSHAW, CAB, BIKE
    registration_number: str
    rent_type: str = "FIXED_RENT"  # FIXED_RENT, REVENUE_SHARE, OWNED
    rent_amount: Decimal = Decimal("0.00")
    rent_frequency: RentFrequency = RentFrequency.DAILY
    assigned_driver_ids: List[str] = Field(default_factory=list)
    active_status: str = "ACTIVE"
    created_at: datetime.datetime = Field(default_factory=now_utc)

    @field_validator("rent_amount", mode="before")
    @classmethod
    def validate_rent(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec < Decimal("0"):
            raise ValueError(f"Rent amount cannot be negative, got: {dec}")
        return dec


class Settlement(BaseModel):
    """
    Owner-driver settlement reconciliation model with versioning.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    settlement_id: str
    driver_id: str
    vehicle_id: str
    settlement_date: str  # YYYY-MM-DD
    shift_id: str = "DEFAULT"
    version: int = 1
    previous_balance: Decimal = Decimal("0.00")
    expected_rent: Decimal = Decimal("0.00")
    gross_income: Decimal = Decimal("0.00")
    operating_expenses: Decimal = Decimal("0.00")
    operating_profit: Decimal = Decimal("0.00")
    owner_payments: Decimal = Decimal("0.00")
    total_obligation: Decimal = Decimal("0.00")
    remaining_balance: Decimal = Decimal("0.00")
    driver_take_home: Decimal = Decimal("0.00")
    settlement_status: SettlementStatus = SettlementStatus.SETTLED
    created_at: datetime.datetime = Field(default_factory=now_utc)
    created_by: str = ""
    idempotency_key: str = ""
    recalculation_reason: Optional[str] = None
    supersedes_settlement_id: Optional[str] = None

    @field_validator(
        "previous_balance", "total_obligation", "remaining_balance",
        "operating_profit", "driver_take_home", mode="before"
    )
    @classmethod
    def validate_signed_balances(cls, v: Any) -> Decimal:
        """Balances and net profit/take-home can be positive (debt), zero (settled), or negative (credit)."""
        return quantize_money(v)

    @field_validator(
        "expected_rent", "gross_income", "operating_expenses", "owner_payments", mode="before"
    )
    @classmethod
    def validate_non_negative_amounts(cls, v: Any) -> Decimal:
        """Revenues, costs, expected rent, and payments must be non-negative."""
        dec = quantize_money(v)
        if dec < Decimal("0.00"):
            raise ValueError(f"Value must be non-negative (>= 0), got: {dec}")
        return dec


class PendingAction(BaseModel):
    """
    Safety buffer model for unconfirmed financial operations.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pending_action_id: str
    driver_id: str
    action_type: PendingActionType
    proposed_data: Dict[str, Any]
    status: PendingActionStatus = PendingActionStatus.PENDING
    human_readable_summary: str
    created_at: datetime.datetime = Field(default_factory=now_utc)
    expires_at: datetime.datetime
    confirmed_at: Optional[datetime.datetime] = None
    consumed_at: Optional[datetime.datetime] = None
    idempotency_key: str
    execution_result: Optional[Dict[str, Any]] = None
