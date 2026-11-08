"""
Repository for Vehicle Maintenance Records in MongoDB.
Handles maintenance logs, upcoming service queries, and expenditure summaries.
"""

import logging
from typing import Dict, Any, List, Optional
from decimal import Decimal
from bson.decimal128 import Decimal128
from pymongo import DESCENDING, ASCENDING

from app.models.maintenance import MaintenanceRecord, MaintenanceCategory, CATEGORY_LABELS
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.maintenance_repo")


def to_mongo_maintenance(data: Dict[str, Any]) -> Dict[str, Any]:
    """Encodes Decimal cost into Decimal128 for MongoDB."""
    d = dict(data)
    if "cost" in d and isinstance(d["cost"], (Decimal, str, int)):
        d["cost"] = Decimal128(str(d["cost"]))
    return d


def from_mongo_maintenance(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Decodes Decimal128 into Python Decimal and adds category human label."""
    d = dict(doc)
    d.pop("_id", None)
    if "cost" in d and isinstance(d["cost"], Decimal128):
        d["cost"] = d["cost"].to_decimal()
    cat = d.get("maintenance_category")
    if cat:
        try:
            d["category_label"] = CATEGORY_LABELS.get(MaintenanceCategory(cat), cat)
        except Exception:
            d["category_label"] = cat
    return d


class MaintenanceRepository:
    """Encapsulates MongoDB operations on the 'maintenance_records' collection."""

    def __init__(self, db):
        self.db = db
        self.collection = db.maintenance_records

    def add_record(self, record: MaintenanceRecord) -> Dict[str, Any]:
        """Inserts a new maintenance log into MongoDB."""
        data = record.model_dump()
        mongo_doc = to_mongo_maintenance(data)
        self.collection.insert_one(mongo_doc)
        return from_mongo_maintenance(mongo_doc)

    def get_by_id(self, maintenance_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves record by maintenance_id."""
        doc = self.collection.find_one({"maintenance_id": maintenance_id})
        return from_mongo_maintenance(doc) if doc else None

    def list_records(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Lists maintenance history for a driver with optional vehicle and category filters.
        """
        query: Dict[str, Any] = {"driver_id": driver_id}
        if vehicle_id:
            query["vehicle_id"] = vehicle_id
        if category:
            query["maintenance_category"] = category.upper()

        cursor = self.collection.find(query).sort("service_date", DESCENDING).limit(limit)
        return [from_mongo_maintenance(d) for d in cursor]

    def update_record(self, maintenance_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates fields of a maintenance record."""
        updates["updated_at"] = now_utc()
        clean = to_mongo_maintenance(updates)
        self.collection.update_one(
            {"maintenance_id": maintenance_id},
            {"$set": clean}
        )
        return self.get_by_id(maintenance_id)

    def get_upcoming_services(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        from_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves scheduled future services (where next_service_date is defined and >= from_date).
        """
        start = from_date or today_ist()
        query: Dict[str, Any] = {
            "driver_id": driver_id,
            "next_service_date": {"$ne": None, "$gte": start}
        }
        if vehicle_id:
            query["vehicle_id"] = vehicle_id

        cursor = self.collection.find(query).sort("next_service_date", ASCENDING)
        return [from_mongo_maintenance(d) for d in cursor]

    def get_spending_summary(
        self,
        driver_id: str,
        start_date: str,
        end_date: str,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculates maintenance spending over a date range.
        Aggregates total cost and count by category.
        """
        query: Dict[str, Any] = {
            "driver_id": driver_id,
            "service_date": {"$gte": start_date, "$lte": end_date}
        }
        if vehicle_id:
            query["vehicle_id"] = vehicle_id

        cursor = self.collection.find(query)
        total_cost = Decimal("0.00")
        total_count = 0
        by_category: Dict[str, Decimal] = {}

        for doc in cursor:
            item = from_mongo_maintenance(doc)
            cost_val = Decimal(str(item.get("cost", 0)))
            total_cost += cost_val
            total_count += 1
            cat = item.get("maintenance_category", "OTHER")
            by_category[cat] = by_category.get(cat, Decimal("0.00")) + cost_val

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_spending": str(total_cost),
            "record_count": total_count,
            "by_category": {k: str(v) for k, v in by_category.items()}
        }
