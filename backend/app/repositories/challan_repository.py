"""
Repository for Traffic Challans in MongoDB.
Handles CRUD operations, payment status transitions, and audit records.
"""

import logging
from typing import Dict, Any, List, Optional
from decimal import Decimal
from bson.decimal128 import Decimal128
from pymongo import DESCENDING

from app.models.challan import Challan, ChallanStatus
from app.utils.dates import now_utc

logger = logging.getLogger("t2t_drive.challan_repo")


def to_mongo_challan(data: Dict[str, Any]) -> Dict[str, Any]:
    """Encodes Decimal fine_amount into Decimal128 for MongoDB."""
    d = dict(data)
    if "fine_amount" in d and isinstance(d["fine_amount"], (Decimal, str, int)):
        d["fine_amount"] = Decimal128(str(d["fine_amount"]))
    return d


def from_mongo_challan(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Decodes Decimal128 into Python Decimal/str."""
    d = dict(doc)
    d.pop("_id", None)
    if "fine_amount" in d and isinstance(d["fine_amount"], Decimal128):
        d["fine_amount"] = d["fine_amount"].to_decimal()
    return d


class ChallanRepository:
    """Encapsulates MongoDB operations on the 'challans' collection."""

    def __init__(self, db):
        self.db = db
        self.collection = db.challans

    def add_challan(self, challan: Challan) -> Dict[str, Any]:
        """Inserts a new challan record into MongoDB."""
        data = challan.model_dump()
        mongo_doc = to_mongo_challan(data)
        self.collection.insert_one(mongo_doc)
        return from_mongo_challan(mongo_doc)

    def get_by_id(self, challan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves challan record by challan_id."""
        doc = self.collection.find_one({"challan_id": challan_id})
        return from_mongo_challan(doc) if doc else None

    def get_by_number(self, challan_number: str) -> Optional[Dict[str, Any]]:
        """Retrieves challan record by official challan number."""
        doc = self.collection.find_one({"challan_number": challan_number})
        return from_mongo_challan(doc) if doc else None

    def list_challans(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lists challans for a driver with optional vehicle and status filtering.
        """
        query: Dict[str, Any] = {"driver_id": driver_id}
        if vehicle_id:
            query["vehicle_id"] = vehicle_id
        if status:
            query["payment_status"] = status.upper()

        cursor = self.collection.find(query).sort("challan_date", DESCENDING)
        return [from_mongo_challan(d) for d in cursor]

    def update_challan(self, challan_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates fields on a challan record."""
        updates["updated_at"] = now_utc()
        clean = to_mongo_challan(updates)
        self.collection.update_one(
            {"challan_id": challan_id},
            {"$set": clean}
        )
        return self.get_by_id(challan_id)

    def update_payment(
        self,
        challan_id: str,
        payment_date: str,
        payment_reference: str,
        notes: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Marks a challan as PAID with payment reference details."""
        updates: Dict[str, Any] = {
            "payment_status": ChallanStatus.PAID.value,
            "payment_date": payment_date,
            "payment_reference": payment_reference,
            "updated_at": now_utc()
        }
        if notes:
            updates["notes"] = notes

        self.collection.update_one(
            {"challan_id": challan_id},
            {"$set": updates}
        )
        return self.get_by_id(challan_id)

    def count_unpaid(self, driver_id: str) -> int:
        """Counts outstanding unpaid challans for driver."""
        return self.collection.count_documents({
            "driver_id": driver_id,
            "payment_status": ChallanStatus.UNPAID.value
        })
