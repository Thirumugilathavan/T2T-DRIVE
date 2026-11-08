"""
Repository for Vehicle & Driver Documents in MongoDB.
Handles CRUD operations, document superseding on renewals, and query filters.
"""

import logging
from typing import Dict, Any, List, Optional
from pymongo import ASCENDING, DESCENDING
import datetime

from app.models.vehicle_document import VehicleDocument, VerificationStatus
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.document_repo")


class DocumentRepository:
    """Encapsulates MongoDB operations on the 'vehicle_documents' collection."""

    def __init__(self, db):
        self.db = db
        self.collection = db.vehicle_documents

    def add_document(self, doc: VehicleDocument) -> Dict[str, Any]:
        """Inserts a new document record into MongoDB."""
        data = doc.model_dump()
        self.collection.insert_one(data)
        data.pop("_id", None)
        return data

    def get_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves document record by document_id."""
        res = self.collection.find_one({"document_id": document_id})
        if res:
            res.pop("_id", None)
        return res

    def list_documents(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lists documents belonging to a driver, optionally filtered by vehicle.
        """
        query: Dict[str, Any] = {"driver_id": driver_id}
        if active_only:
            query["is_active"] = True

        if vehicle_id:
            # Match either specific vehicle_id or driver personal documents (vehicle_id=None)
            query["$or"] = [{"vehicle_id": vehicle_id}, {"vehicle_id": None}]

        cursor = self.collection.find(query).sort("created_at", DESCENDING)
        docs = []
        for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return docs

    def update_metadata(self, document_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates metadata fields for a document."""
        updates["updated_at"] = now_utc()
        self.collection.update_one(
            {"document_id": document_id},
            {"$set": updates}
        )
        return self.get_by_id(document_id)

    def supersede_document(self, old_document_id: str, new_document_id: str) -> bool:
        """
        Marks an older document as superseded when renewed by a new document.
        Preserves history while preventing duplicate reminders.
        """
        res = self.collection.update_one(
            {"document_id": old_document_id},
            {
                "$set": {
                    "is_active": False,
                    "superseded_by": new_document_id,
                    "verification_status": VerificationStatus.SUPERSEDED.value,
                    "updated_at": now_utc()
                }
            }
        )
        return res.modified_count > 0

    def mark_inactive(self, document_id: str) -> bool:
        """Marks a document as inactive (soft delete)."""
        res = self.collection.update_one(
            {"document_id": document_id},
            {"$set": {"is_active": False, "updated_at": now_utc()}}
        )
        return res.modified_count > 0

    def find_expiring_documents(
        self,
        target_expiry_date: str,
        driver_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Finds active documents that expire exactly on target_expiry_date (YYYY-MM-DD).
        Used by the reminder service for milestone thresholds.
        """
        query: Dict[str, Any] = {
            "is_active": True,
            "expiry_date": target_expiry_date
        }
        if driver_id:
            query["driver_id"] = driver_id

        cursor = self.collection.find(query)
        docs = []
        for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return docs
