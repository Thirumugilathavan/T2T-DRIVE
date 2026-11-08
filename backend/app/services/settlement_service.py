"""
Owner-Driver Settlement and Reconciliation Engine for T2T DRIVE.
Enforces deterministic rental reconciliation where the transaction ledger is the
single source of truth for all owner payments, operating costs, and income.
Provides immutable settlement versioning and carried-forward balance tracking.
"""

import secrets
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal
from pymongo import ASCENDING, DESCENDING

from app.models.financial import (
    Settlement,
    SettlementStatus,
    Vehicle,
    RentFrequency,
    quantize_money,
    format_money
)
from app.repositories.transaction_repository import to_mongo_doc, from_mongo_doc
from app.services.financial_calculator import FinancialCalculator
from app.services.audit_service import AuditService
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger(__name__)


class SettlementService:
    """
    Reconciles vehicle rental settlements between drivers and vehicle owners.
    """

    def __init__(self, db, repo, audit_service: Optional[AuditService] = None):
        self.db = db
        self.repo = repo
        self.audit = audit_service

    def get_or_create_vehicle(
        self,
        vehicle_id: str,
        driver_id: str,
        default_rent: Decimal = Decimal("350.00"),
        rent_frequency: RentFrequency = RentFrequency.DAILY
    ) -> Dict[str, Any]:
        """
        Retrieves or initializes a vehicle profile, validating driver authorization.
        """
        veh = self.db.vehicles.find_one({"vehicle_id": vehicle_id})
        if veh:
            # Check if driver is assigned
            assigned = veh.get("assigned_driver_ids", [])
            if driver_id not in assigned:
                # Associate driver
                self.db.vehicles.update_one(
                    {"_id": veh["_id"]},
                    {"$addToSet": {"assigned_driver_ids": driver_id}}
                )
            return from_mongo_doc(veh)

        # Create new vehicle with default terms
        new_veh = Vehicle(
            vehicle_id=vehicle_id,
            owner_id=f"OWNER_{secrets.token_hex(4)}",
            vehicle_type="AUTO_RICKSHAW",
            registration_number=vehicle_id,
            rent_type="FIXED_RENT",
            rent_amount=quantize_money(default_rent),
            rent_frequency=rent_frequency,
            assigned_driver_ids=[driver_id],
            active_status="ACTIVE",
            created_at=now_utc()
        )
        doc = new_veh.model_dump()
        self.db.vehicles.insert_one(to_mongo_doc(doc))
        return doc

    def create_settlement(
        self,
        driver_id: str,
        vehicle_id: str,
        settlement_date: Optional[str] = None,
        shift_id: str = "DEFAULT",
        previous_balance: Optional[Decimal] = None,
        idempotency_key: str = "",
        actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates an initial (version 1) settlement from the transaction ledger.
        Prevents duplicate initial settlements for the same (driver, vehicle, date, shift).
        """
        date_str = (settlement_date or today_ist()).strip()

        # 1. Check for existing version 1 settlement
        existing = self.db.settlements.find_one({
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "settlement_date": date_str,
            "shift_id": shift_id,
            "version": 1
        })
        if existing:
            raise ValueError(
                f"Settlement already exists for driver '{driver_id}', vehicle '{vehicle_id}', "
                f"date '{date_str}', shift '{shift_id}'. Use recalculate to create a new version."
            )

        # 2. Get Vehicle Details & Expected Rent
        veh = self.get_or_create_vehicle(vehicle_id, driver_id)
        expected_rent = quantize_money(veh.get("rent_amount", Decimal("350.00")))

        # 3. Determine Previous Balance (Carried-Forward Balance)
        if previous_balance is not None:
            prev_bal = quantize_money(previous_balance)
        else:
            prev_bal = self._lookup_previous_balance(driver_id, vehicle_id, date_str)

        # 4. Fetch Ledger Data for this Date and Vehicle (Single Source of Truth)
        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=date_str,
            end_date=date_str,
            limit=5000
        )
        metrics = FinancialCalculator.calculate_metrics(txns)
        gross_income = metrics["_raw"]["gross_income"]
        operating_expenses = metrics["_raw"]["operating_expenses"]
        owner_payments = metrics["_raw"]["owner_payments"]

        # 5. Calculate Settlement Results Deterministically
        calc = FinancialCalculator.calculate_settlement(
            previous_balance=prev_bal,
            expected_rent=expected_rent,
            gross_income=gross_income,
            operating_expenses=operating_expenses,
            owner_payments=owner_payments
        )

        settlement_id = f"SETTLE_{secrets.token_hex(8)}"
        settlement_obj = Settlement(
            settlement_id=settlement_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            settlement_date=date_str,
            shift_id=shift_id,
            version=1,
            previous_balance=prev_bal,
            expected_rent=expected_rent,
            gross_income=gross_income,
            operating_expenses=operating_expenses,
            operating_profit=calc["_raw"]["operating_profit"],
            owner_payments=owner_payments,
            total_obligation=calc["_raw"]["total_obligation"],
            remaining_balance=calc["_raw"]["remaining_balance"],
            driver_take_home=calc["_raw"]["driver_take_home"],
            settlement_status=calc["_raw"]["settlement_status"],
            created_at=now_utc(),
            created_by=actor or driver_id,
            idempotency_key=idempotency_key
        )

        doc = settlement_obj.model_dump()
        self.db.settlements.insert_one(to_mongo_doc(doc))

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="SETTLEMENT_CREATED",
                resource_type="SETTLEMENT",
                resource_id=settlement_id,
                actor=actor or driver_id,
                metadata={
                    "vehicle_id": vehicle_id,
                    "date": date_str,
                    "version": 1,
                    "status": calc["settlement_status"],
                    "remaining_balance": calc["remaining_balance"]
                }
            )

        logger.info("Created settlement %s (v1) for %s on vehicle %s", settlement_id, driver_id, vehicle_id)
        return self._format_settlement(doc)

    def recalculate_settlement(
        self,
        settlement_id: str,
        driver_id: str,
        reason: str,
        idempotency_key: str = "",
        actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a new immutable settlement version (e.g. version 2).
        The prior settlement version is completely preserved in history.
        """
        prior = self.db.settlements.find_one({"settlement_id": settlement_id, "driver_id": driver_id})
        if not prior:
            raise ValueError(f"Settlement '{settlement_id}' not found or unauthorized.")

        prior_doc = from_mongo_doc(prior)
        v_next = prior_doc["version"] + 1
        vehicle_id = prior_doc["vehicle_id"]
        date_str = prior_doc["settlement_date"]
        shift_id = prior_doc["shift_id"]
        prev_bal = prior_doc["previous_balance"]
        expected_rent = prior_doc["expected_rent"]

        # Re-fetch latest ledger transactions (may include new adjustments or reversals)
        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=date_str,
            end_date=date_str,
            limit=5000
        )
        metrics = FinancialCalculator.calculate_metrics(txns)
        gross_income = metrics["_raw"]["gross_income"]
        operating_expenses = metrics["_raw"]["operating_expenses"]
        owner_payments = metrics["_raw"]["owner_payments"]

        # Recalculate
        calc = FinancialCalculator.calculate_settlement(
            previous_balance=prev_bal,
            expected_rent=expected_rent,
            gross_income=gross_income,
            operating_expenses=operating_expenses,
            owner_payments=owner_payments
        )

        new_settle_id = f"SETTLE_{secrets.token_hex(8)}"
        new_settle_obj = Settlement(
            settlement_id=new_settle_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            settlement_date=date_str,
            shift_id=shift_id,
            version=v_next,
            previous_balance=prev_bal,
            expected_rent=expected_rent,
            gross_income=gross_income,
            operating_expenses=operating_expenses,
            operating_profit=calc["_raw"]["operating_profit"],
            owner_payments=owner_payments,
            total_obligation=calc["_raw"]["total_obligation"],
            remaining_balance=calc["_raw"]["remaining_balance"],
            driver_take_home=calc["_raw"]["driver_take_home"],
            settlement_status=calc["_raw"]["settlement_status"],
            created_at=now_utc(),
            created_by=actor or driver_id,
            idempotency_key=idempotency_key,
            recalculation_reason=reason,
            supersedes_settlement_id=settlement_id
        )

        doc = new_settle_obj.model_dump()
        self.db.settlements.insert_one(to_mongo_doc(doc))

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="SETTLEMENT_RECALCULATED",
                resource_type="SETTLEMENT",
                resource_id=new_settle_id,
                actor=actor or driver_id,
                metadata={
                    "supersedes": settlement_id,
                    "version": v_next,
                    "reason": reason,
                    "status": calc["settlement_status"],
                    "remaining_balance": calc["remaining_balance"]
                }
            )

        logger.info("Recalculated settlement %s (v%s) superseding %s", new_settle_id, v_next, settlement_id)
        return self._format_settlement(doc)

    def get_settlement(self, settlement_id: str, driver_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single settlement by ID scoped to driver."""
        doc = self.db.settlements.find_one({
            "settlement_id": settlement_id,
            "driver_id": driver_id
        })
        return self._format_settlement(from_mongo_doc(doc)) if doc else None

    def list_driver_settlements(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists settlements for an authenticated driver."""
        query: Dict[str, Any] = {"driver_id": driver_id}
        if vehicle_id:
            query["vehicle_id"] = vehicle_id

        cursor = self.db.settlements.find(query).sort([
            ("settlement_date", DESCENDING),
            ("version", DESCENDING)
        ]).skip(skip).limit(limit)

        return [self._format_settlement(from_mongo_doc(d)) for d in cursor if d]

    def _lookup_previous_balance(self, driver_id: str, vehicle_id: str, before_date: str) -> Decimal:
        """Finds remaining balance from the most recent prior settlement."""
        prior = self.db.settlements.find_one(
            {
                "driver_id": driver_id,
                "vehicle_id": vehicle_id,
                "settlement_date": {"$lt": before_date}
            },
            sort=[("settlement_date", DESCENDING), ("version", DESCENDING)]
        )
        if prior:
            prior_doc = from_mongo_doc(prior)
            return quantize_money(prior_doc.get("remaining_balance", Decimal("0.00")))
        return Decimal("0.00")

    @staticmethod
    def _format_settlement(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Formats Decimal fields to 2-decimal strings for API responses."""
        res = dict(doc)
        money_keys = [
            "previous_balance", "expected_rent", "gross_income",
            "operating_expenses", "operating_profit", "owner_payments",
            "total_obligation", "remaining_balance", "driver_take_home"
        ]
        for k in money_keys:
            if k in res:
                res[k] = format_money(res[k])
        if "settlement_status" in res and hasattr(res["settlement_status"], "value"):
            res["settlement_status"] = res["settlement_status"].value
        if "created_at" in res and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        return res
