"""
Pydantic v2 Request/Response Validation Schemas for Financial Endpoints.
Protects endpoints against malformed payloads, float contamination,
and unvalidated amounts.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.financial import (
    TransactionType,
    IncomeCategory,
    ExpenseCategory,
    OwnerPaymentCategory,
    quantize_money,
    today_ist
)


class ProposeTransactionRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vehicle_id: str = Field(..., min_length=1, description="Vehicle ID or registration number")
    transaction_type: TransactionType = Field(..., description="INCOME, EXPENSE, or OWNER_PAYMENT")
    amount: Decimal = Field(..., description="Positive amount as string or number (e.g. '450.00')")
    category: str = Field(..., min_length=1, description="Financial category (FUEL, FARE, etc.)")
    description: str = Field(default="", description="Optional description")
    transaction_date: str = Field(default_factory=today_ist, description="Transaction date YYYY-MM-DD")
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key")
    source: str = Field(default="MANUAL", description="VOICE or MANUAL")
    reference_id: Optional[str] = Field(default=None, description="Original transaction ID if reversal/adjustment")

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec <= Decimal("0"):
            raise ValueError(f"Amount must be strictly positive (> 0), got: {dec}")
        return dec

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        clean = v.strip().upper()
        if not clean:
            raise ValueError("Category cannot be empty.")
        return clean

    @field_validator("transaction_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        clean = v.strip()
        from app.utils.dates import parse_date_str
        parse_date_str(clean)
        return clean


class ConfirmPendingActionRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key for confirmation")


class AdjustTransactionRequest(BaseModel):
    new_amount: Decimal = Field(..., description="Corrected positive amount")
    reason: str = Field(..., min_length=3, description="Reason for adjustment")
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key")

    @field_validator("new_amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Decimal:
        dec = quantize_money(v)
        if dec <= Decimal("0"):
            raise ValueError(f"Adjusted amount must be strictly positive (> 0), got: {dec}")
        return dec


class ReverseTransactionRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Reason for reversal")
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key")


class ProposeSettlementRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vehicle_id: str = Field(..., min_length=1, description="Vehicle ID")
    settlement_date: str = Field(default_factory=today_ist, description="Settlement calendar date YYYY-MM-DD")
    shift_id: str = Field(default="DEFAULT", description="Shift identifier (DEFAULT, DAY, NIGHT)")
    previous_balance: Optional[Decimal] = Field(default=Decimal("0.00"), description="Carried-forward debt (+) or credit (-)")
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key")

    @field_validator("previous_balance", mode="before")
    @classmethod
    def validate_balance(cls, v: Any) -> Decimal:
        if v is None:
            return Decimal("0.00")
        return quantize_money(v)


class RecalculateSettlementRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Reason for recalculation")
    idempotency_key: str = Field(..., min_length=1, description="Unique client idempotency key")
