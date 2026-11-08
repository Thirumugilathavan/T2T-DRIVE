"""
Vehicle Maintenance Service for T2T DRIVE.
Manages garage service logs, preventive service schedules, odometer validation,
and seamless integration with the Phase 2 financial ledger.
"""

import secrets
import logging
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal

from app.models.maintenance import (
    MaintenanceRecord,
    MaintenanceCategory,
    normalize_maintenance_category,
    CATEGORY_LABELS
)
from app.models.financial import PendingActionType
from app.repositories.maintenance_repository import MaintenanceRepository
from app.utils.storage import StorageAdapterBase
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.maintenance_service")


class MaintenanceService:
    """Coordinates vehicle service logs, reminders, and ledger synchronization."""

    def __init__(
        self,
        db,
        maintenance_repo: MaintenanceRepository,
        storage: Optional[StorageAdapterBase] = None,
        pending_action_service=None,
        ledger_service=None,
        audit_service=None
    ):
        self.db = db
        self.repo = maintenance_repo
        self.storage = storage
        self.pending_svc = pending_action_service
        self.ledger_svc = ledger_service
        self.audit = audit_service

    def add_maintenance_record(
        self,
        driver_id: str,
        vehicle_id: str,
        maintenance_category_str: str,
        description: str,
        cost: Decimal,
        service_date: Optional[str] = None,
        odometer_reading: Optional[int] = None,
        service_provider: Optional[str] = "Local Garage",
        next_service_date: Optional[str] = None,
        next_service_odometer: Optional[int] = None,
        financial_transaction_id: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        notes: Optional[str] = ""
    ) -> Dict[str, Any]:
        """
        Creates a new maintenance record in MongoDB.
        Can optionally link an existing or committed financial transaction ID.
        """
        category = normalize_maintenance_category(maintenance_category_str)

        file_ref = None
        if file_bytes and filename and self.storage:
            file_ref, _, _ = self.storage.save_file(file_bytes=file_bytes, original_filename=filename)

        maintenance_id = f"MNT_{secrets.token_hex(8)}"
        now = now_utc()

        record = MaintenanceRecord(
            maintenance_id=maintenance_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            maintenance_category=category,
            description=description,
            service_date=service_date or today_ist(),
            odometer_reading=odometer_reading,
            service_provider=service_provider or "Local Garage",
            cost=cost,
            next_service_date=next_service_date,
            next_service_odometer=next_service_odometer,
            receipt_reference=file_ref,
            financial_transaction_id=financial_transaction_id,
            notes=notes or "",
            created_at=now,
            updated_at=now
        )

        saved = self.repo.add_record(record)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                action="MAINTENANCE_LOGGED",
                resource_type="maintenance",
                resource_id=maintenance_id,
                details={
                    "vehicle_id": vehicle_id,
                    "category": category.value,
                    "cost": str(cost),
                    "txn_id": financial_transaction_id
                }
            )

        return self._format_maintenance_response(saved)

    def propose_maintenance_with_expense(
        self,
        driver_id: str,
        vehicle_id: str,
        maintenance_category_str: str,
        description: str,
        cost: Decimal,
        service_date: Optional[str] = None,
        odometer_reading: Optional[int] = None,
        service_provider: Optional[str] = "Local Garage",
        next_service_date: Optional[str] = None,
        next_service_odometer: Optional[int] = None,
        notes: Optional[str] = "",
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        FINANCIAL FIREWALL ENFORCEMENT:
        Proposes a maintenance expense transaction through PendingActionService.
        Stores maintenance metadata in proposed_data.
        The maintenance record will be committed and linked only when confirmed!
        """
        if not self.pending_svc:
            raise RuntimeError("PendingActionService is not configured for financial maintenance.")

        category = normalize_maintenance_category(maintenance_category_str)
        date_str = service_date or today_ist()
        idem_key = idempotency_key or f"PROP_MNT_{driver_id}_{secrets.token_hex(6)}"

        proposed_data = {
            "vehicle_id": vehicle_id,
            "amount": str(cost),
            "category": "MAINTENANCE",
            "description": f"Vehicle Maintenance: {description} ({category.value})",
            "transaction_date": date_str,
            "source": "MAINTENANCE_MODULE",
            "maintenance_details": {
                "maintenance_category": category.value,
                "description": description,
                "service_date": date_str,
                "odometer_reading": odometer_reading,
                "service_provider": service_provider or "Local Garage",
                "next_service_date": next_service_date,
                "next_service_odometer": next_service_odometer,
                "notes": notes or ""
            }
        }

        pending = self.pending_svc.propose_action(
            driver_id=driver_id,
            action_type=PendingActionType.ADD_EXPENSE,
            proposed_data=proposed_data,
            idempotency_key=idem_key
        )

        return {
            "action_required": "CONFIRM_TRANSACTION",
            "pending_action_id": pending["pending_action_id"],
            "summary": pending["human_readable_summary"],
            "proposed_data": proposed_data,
            "expires_at": pending["expires_at"]
        }

    def link_maintenance_to_transaction(
        self,
        driver_id: str,
        transaction_id: str,
        proposed_maintenance_data: Dict[str, Any],
        cost: Decimal
    ) -> Dict[str, Any]:
        """
        Idempotently creates a maintenance record linked to a committed transaction.
        Checks if already linked to prevent duplicate entries on retry.
        """
        # 1. Deduplication check
        existing = self.repo.collection.find_one({
            "driver_id": driver_id,
            "financial_transaction_id": transaction_id
        })
        if existing:
            existing.pop("_id", None)
            return self._format_maintenance_response(existing)

        v_id = proposed_maintenance_data.get("vehicle_id", "DEFAULT_VEHICLE")
        details = proposed_maintenance_data.get("maintenance_details", {})

        return self.add_maintenance_record(
            driver_id=driver_id,
            vehicle_id=v_id,
            maintenance_category_str=details.get("maintenance_category", "GENERAL_SERVICING"),
            description=details.get("description", "Vehicle Maintenance"),
            cost=cost,
            service_date=details.get("service_date", today_ist()),
            odometer_reading=details.get("odometer_reading"),
            service_provider=details.get("service_provider", "Local Garage"),
            next_service_date=details.get("next_service_date"),
            next_service_odometer=details.get("next_service_odometer"),
            financial_transaction_id=transaction_id,
            notes=details.get("notes", "")
        )

    def get_maintenance(self, maintenance_id: str, driver_id: str) -> Dict[str, Any]:
        """Retrieves maintenance log verifying driver authorization."""
        doc = self.repo.get_by_id(maintenance_id)
        if not doc:
            raise FileNotFoundError(f"Maintenance record '{maintenance_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this maintenance record.")
        return self._format_maintenance_response(doc)

    def list_maintenance(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists maintenance history for driver."""
        docs = self.repo.list_records(driver_id=driver_id, vehicle_id=vehicle_id, category=category)
        return [self._format_maintenance_response(d) for d in docs]

    def update_maintenance(
        self,
        maintenance_id: str,
        driver_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Updates maintenance record details."""
        doc = self.repo.get_by_id(maintenance_id)
        if not doc:
            raise FileNotFoundError(f"Maintenance record '{maintenance_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this maintenance record.")

        allowed = {
            "description", "service_provider", "odometer_reading",
            "next_service_date", "next_service_odometer", "notes"
        }
        clean = {k: v for k, v in updates.items() if k in allowed and v is not None}
        updated = self.repo.update_record(maintenance_id, clean)
        return self._format_maintenance_response(updated)

    def get_upcoming_services(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves future scheduled services."""
        docs = self.repo.get_upcoming_services(driver_id=driver_id, vehicle_id=vehicle_id)
        return [self._format_maintenance_response(d) for d in docs]

    def get_overdue_services(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        current_odometer: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Identifies services that are overdue either by date or odometer.
        """
        today = today_ist()
        query: Dict[str, Any] = {
            "driver_id": driver_id,
            "next_service_date": {"$ne": None, "$lt": today}
        }
        if vehicle_id:
            query["vehicle_id"] = vehicle_id

        cursor = self.repo.collection.find(query)
        overdue_list = []
        for d in cursor:
            overdue_list.append(self._format_maintenance_response(d))

        # Check odometer-based overdue services if current_odometer supplied
        if current_odometer:
            odo_query: Dict[str, Any] = {
                "driver_id": driver_id,
                "next_service_odometer": {"$ne": None, "$lte": current_odometer}
            }
            if vehicle_id:
                odo_query["vehicle_id"] = vehicle_id
            for d in self.repo.collection.find(odo_query):
                formatted = self._format_maintenance_response(d)
                if not any(item["maintenance_id"] == formatted["maintenance_id"] for item in overdue_list):
                    overdue_list.append(formatted)

        return overdue_list

    def get_spending_summary(
        self,
        driver_id: str,
        start_date: str,
        end_date: str,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calculates maintenance expenditure breakdown over date range."""
        return self.repo.get_spending_summary(driver_id, start_date, end_date, vehicle_id)

    def _format_maintenance_response(self, doc_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Formats maintenance record for API response."""
        d = dict(doc_dict)
        d["cost"] = str(d.get("cost", "0.00"))
        d["has_receipt"] = bool(d.get("receipt_reference"))
        d.pop("receipt_reference", None)
        cat = d.get("maintenance_category", "")
        try:
            d["category_label"] = CATEGORY_LABELS.get(MaintenanceCategory(cat), cat)
        except Exception:
            d["category_label"] = cat
        return d
