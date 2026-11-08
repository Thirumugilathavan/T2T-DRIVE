"""
Repository for Vehicle Reminders in MongoDB.
Enforces idempotent reminder generation using unique idempotency keys,
preventing duplicate notifications for the same threshold milestone.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from pymongo import DESCENDING, ASCENDING
from pymongo.errors import DuplicateKeyError

from app.models.reminder import VehicleReminder, ReminderStatus
from app.utils.dates import now_utc

logger = logging.getLogger("t2t_drive.reminder_repo")


class ReminderRepository:
    """Encapsulates MongoDB operations on the 'vehicle_reminders' collection."""

    def __init__(self, db):
        self.db = db
        self.collection = db.vehicle_reminders

    def create_reminder_if_absent(self, reminder: VehicleReminder) -> Tuple[Dict[str, Any], bool]:
        """
        Idempotently inserts a reminder record.
        Returns: (record_dict, was_created: bool)
        """
        if reminder.idempotency_key:
            existing = self.collection.find_one({"idempotency_key": reminder.idempotency_key})
            if existing:
                existing.pop("_id", None)
                return existing, False

        data = reminder.model_dump()
        try:
            self.collection.insert_one(data)
            data.pop("_id", None)
            return data, True
        except DuplicateKeyError:
            # Already generated for this threshold and due date
            existing = self.collection.find_one({"idempotency_key": reminder.idempotency_key})
            if existing:
                existing.pop("_id", None)
                return existing, False
            data.pop("_id", None)
            return data, False

    def get_by_id(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves reminder by reminder_id."""
        doc = self.collection.find_one({"reminder_id": reminder_id})
        if doc:
            doc.pop("_id", None)
        return doc

    def list_reminders(
        self,
        driver_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Lists reminders for a driver, optionally filtered by status."""
        query: Dict[str, Any] = {"driver_id": driver_id}
        if status:
            query["status"] = status.upper()

        cursor = self.collection.find(query).sort("due_date", ASCENDING).limit(limit)
        items = []
        for d in cursor:
            d.pop("_id", None)
            items.append(d)
        return items

    def acknowledge_reminder(self, reminder_id: str, driver_id: str) -> bool:
        """Marks a reminder as ACKNOWLEDGED."""
        res = self.collection.update_one(
            {"reminder_id": reminder_id, "driver_id": driver_id},
            {"$set": {"status": ReminderStatus.ACKNOWLEDGED.value, "updated_at": now_utc()}}
        )
        return res.modified_count > 0

    def mark_delivered(self, reminder_id: str, channel: str) -> bool:
        """Marks a reminder as DELIVERED via a specified channel (e.g. SMS, IN_APP, MOCK)."""
        now = now_utc()
        res = self.collection.update_one(
            {"reminder_id": reminder_id},
            {
                "$set": {
                    "status": ReminderStatus.DELIVERED.value,
                    "delivered_via": channel,
                    "delivered_at": now,
                    "updated_at": now
                }
            }
        )
        return res.modified_count > 0

    def cancel_reminders_for_reference(self, reference_id: str) -> int:
        """
        Dismisses/cancels all pending reminders for a superseded document or completed service.
        """
        res = self.collection.update_many(
            {"reference_id": reference_id, "status": ReminderStatus.PENDING.value},
            {"$set": {"status": ReminderStatus.DISMISSED.value, "updated_at": now_utc()}}
        )
        return res.modified_count
