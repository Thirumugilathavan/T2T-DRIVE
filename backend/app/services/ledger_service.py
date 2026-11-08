"""
Append-Only Ledger Service for T2T DRIVE.
Enforces the immutable financial ledger, handles reversals and adjustments
without mutating original records, and provides the single source of truth.
"""

import secrets
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal
from app.models.financial import (
    FinancialTransaction,
    TransactionType,
    quantize_money,
    format_money
)
from app.repositories.transaction_repository import TransactionRepository
from app.services.financial_calculator import FinancialCalculator
from app.services.audit_service import AuditService
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger(__name__)


class LedgerService:
    """
    Business service executing append-only ledger operations.
    """

    def __init__(self, repo: TransactionRepository, audit_service: Optional[AuditService] = None):
        self.repo = repo
        self.audit = audit_service

    def record_transaction(
        self,
        driver_id: str,
        vehicle_id: str,
        transaction_type: TransactionType,
        amount: Decimal,
        category: str,
        description: str,
        idempotency_key: str,
        transaction_date: Optional[str] = None,
        source: str = "MANUAL",
        reference_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Appends a verified financial transaction to the ledger.
        """
        amt = quantize_money(amount)
        signed_amt = FinancialCalculator.calculate_signed_amount(transaction_type, amt)
        txn_id = f"TXN_{secrets.token_hex(8)}"
        date_str = transaction_date or today_ist()

        # Validate with Pydantic domain model
        txn_obj = FinancialTransaction(
            transaction_id=txn_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            transaction_type=transaction_type,
            amount=amt,
            signed_amount=signed_amt,
            category=category,
            description=description,
            transaction_date=date_str,
            created_at=now_utc(),
            created_by=created_by or driver_id,
            idempotency_key=idempotency_key,
            source=source,
            reference_id=reference_id,
            status="COMPLETED"
        )

        txn_dict = txn_obj.model_dump()
        self.repo.insert_transaction(txn_dict)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="TRANSACTION_CREATED",
                resource_type="TRANSACTION",
                resource_id=txn_id,
                actor=created_by or driver_id,
                metadata={
                    "type": transaction_type.value,
                    "amount": format_money(amt),
                    "signed_amount": format_money(signed_amt),
                    "category": category,
                    "vehicle_id": vehicle_id
                }
            )

        logger.info("Recorded ledger transaction %s: %s %s for %s", txn_id, transaction_type.value, amt, driver_id)
        return self._format_transaction(txn_dict)

    def get_transaction(self, transaction_id: str, driver_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves and formats a single transaction."""
        doc = self.repo.get_by_id(transaction_id, driver_id=driver_id)
        return self._format_transaction(doc) if doc else None

    def list_driver_transactions(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        categories: Optional[List[str]] = None,
        transaction_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Returns paginated transactions with metadata."""
        skip = max(0, (page - 1) * limit)
        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=start_date,
            end_date=end_date,
            categories=categories,
            transaction_types=transaction_types,
            limit=limit,
            skip=skip
        )
        total = self.repo.count_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=start_date,
            end_date=end_date
        )

        formatted_txns = [self._format_transaction(t) for t in txns]
        return {
            "transactions": formatted_txns,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "has_more": (skip + limit) < total
            }
        }

    def create_reversal(
        self,
        original_txn_id: str,
        driver_id: str,
        reason: str,
        idempotency_key: str,
        actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates an append-only reversal entry in the ledger.
        The original transaction remains completely unchanged.
        """
        original = self.repo.get_by_id(original_txn_id, driver_id=driver_id)
        if not original:
            raise ValueError(f"Transaction '{original_txn_id}' not found or does not belong to driver.")

        orig_type = original["transaction_type"]
        if orig_type in ("INCOME_REVERSAL", "EXPENSE_REVERSAL", "OWNER_PAYMENT_REVERSAL"):
            raise ValueError("Cannot reverse a transaction that is already a reversal.")

        # Check if already reversed
        existing_rev = self.repo.find_active_reversal(original_txn_id)
        if existing_rev:
            raise ValueError(f"Transaction '{original_txn_id}' has already been reversed by '{existing_rev['transaction_id']}'.")

        # Map to proper reversal transaction type
        if orig_type == "INCOME":
            rev_type = TransactionType.INCOME_REVERSAL
        elif orig_type == "EXPENSE":
            rev_type = TransactionType.EXPENSE_REVERSAL
        elif orig_type == "OWNER_PAYMENT":
            rev_type = TransactionType.OWNER_PAYMENT_REVERSAL
        else:
            raise ValueError(f"Unsupported transaction type for reversal: {orig_type}")

        rev_amount = quantize_money(original["amount"])
        rev_signed = FinancialCalculator.calculate_signed_amount(rev_type, rev_amount)
        rev_id = f"TXN_{secrets.token_hex(8)}"

        rev_obj = FinancialTransaction(
            transaction_id=rev_id,
            driver_id=driver_id,
            vehicle_id=original["vehicle_id"],
            transaction_type=rev_type,
            amount=rev_amount,
            signed_amount=rev_signed,
            category=original["category"],
            description=f"Reversal of {original_txn_id}: {reason}",
            transaction_date=today_ist(),
            created_at=now_utc(),
            created_by=actor or driver_id,
            idempotency_key=idempotency_key,
            source="SYSTEM",
            reference_id=original_txn_id,
            status="COMPLETED"
        )

        rev_dict = rev_obj.model_dump()
        self.repo.insert_transaction(rev_dict)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="TRANSACTION_REVERSED",
                resource_type="TRANSACTION",
                resource_id=rev_id,
                actor=actor or driver_id,
                metadata={
                    "original_transaction_id": original_txn_id,
                    "reversal_type": rev_type.value,
                    "amount": format_money(rev_amount),
                    "reason": reason
                }
            )

        logger.info("Created reversal %s for original transaction %s", rev_id, original_txn_id)
        return self._format_transaction(rev_dict)

    def create_adjustment(
        self,
        original_txn_id: str,
        driver_id: str,
        new_amount: Decimal,
        reason: str,
        idempotency_key: str,
        actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a two-step append-only correction:
        1. Reverses the original transaction in full.
        2. Appends a new corrected transaction with the new amount.
        Net effect reflects the new amount accurately while preserving complete audit history.
        """
        original = self.repo.get_by_id(original_txn_id, driver_id=driver_id)
        if not original:
            raise ValueError(f"Transaction '{original_txn_id}' not found or does not belong to driver.")

        # Step 1: Create reversal with dedicated sub-key
        rev_key = f"{idempotency_key}_rev"
        rev_result = self.create_reversal(
            original_txn_id=original_txn_id,
            driver_id=driver_id,
            reason=f"Adjustment correction: {reason}",
            idempotency_key=rev_key,
            actor=actor
        )

        # Step 2: Append corrected transaction with dedicated sub-key
        adj_key = f"{idempotency_key}_adj"
        orig_type = TransactionType(original["transaction_type"])
        corr_result = self.record_transaction(
            driver_id=driver_id,
            vehicle_id=original["vehicle_id"],
            transaction_type=orig_type,
            amount=new_amount,
            category=original["category"],
            description=f"Corrected amount for {original_txn_id}: {reason}",
            idempotency_key=adj_key,
            transaction_date=original.get("transaction_date", today_ist()),
            source="SYSTEM",
            reference_id=original_txn_id,
            created_by=actor or driver_id
        )

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="TRANSACTION_ADJUSTED",
                resource_type="TRANSACTION",
                resource_id=corr_result["transaction_id"],
                actor=actor or driver_id,
                metadata={
                    "original_transaction_id": original_txn_id,
                    "reversal_transaction_id": rev_result["transaction_id"],
                    "old_amount": format_money(original["amount"]),
                    "new_amount": format_money(new_amount),
                    "reason": reason
                }
            )

        return {
            "status": "ADJUSTED",
            "original_transaction_id": original_txn_id,
            "reversal": rev_result,
            "corrected_transaction": corr_result
        }

    @staticmethod
    def _format_transaction(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Formats Decimals and datetimes into safe JSON strings."""
        res = dict(doc)
        if "amount" in res:
            res["amount"] = format_money(res["amount"])
        if "signed_amount" in res:
            res["signed_amount"] = format_money(res["signed_amount"])
        if "created_at" in res and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        return res
