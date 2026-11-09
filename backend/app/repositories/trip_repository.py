"""
MongoDB repository for Trip Agreements, Passenger Access, Events, and Payments.
Handles BSON Decimal128 serialization and clean document mapping.
"""

from typing import Dict, Any, List, Optional
import bson
from decimal import Decimal
from pymongo import ASCENDING, DESCENDING


def to_mongo_trip(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively converts Python Decimal into BSON Decimal128 for MongoDB storage."""
    doc = dict(data)
    for k, v in doc.items():
        if isinstance(v, Decimal):
            doc[k] = bson.Decimal128(str(v))
        elif isinstance(v, dict):
            doc[k] = to_mongo_trip(v)
        elif isinstance(v, list):
            doc[k] = [
                to_mongo_trip(i) if isinstance(i, dict)
                else (bson.Decimal128(str(i)) if isinstance(i, Decimal) else i)
                for i in v
            ]
    return doc


def from_mongo_trip(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Recursively converts BSON Decimal128 back into Python Decimal upon retrieval."""
    if data is None:
        return None
    doc = dict(data)
    if "_id" in doc:
        del doc["_id"]
    for k, v in doc.items():
        if isinstance(v, bson.Decimal128):
            doc[k] = v.to_decimal()
        elif isinstance(v, dict):
            doc[k] = from_mongo_trip(v)
        elif isinstance(v, list):
            doc[k] = [
                from_mongo_trip(i) if isinstance(i, dict)
                else (i.to_decimal() if isinstance(i, bson.Decimal128) else i)
                for i in v
            ]
    return doc


class TripRepository:
    """
    Data access layer for trips, passenger access tokens, versioned agreements,
    trip events, and passenger payments.
    """

    def __init__(self, db):
        self.db = db

    # ========================================================================
    # TRIPS
    # ========================================================================

    def insert_trip(self, trip_doc: Dict[str, Any]) -> str:
        mongo_doc = to_mongo_trip(trip_doc)
        self.db.trips.insert_one(mongo_doc)
        return trip_doc["trip_id"]

    def get_trip(self, trip_id: str) -> Optional[Dict[str, Any]]:
        raw = self.db.trips.find_one({"trip_id": trip_id})
        return from_mongo_trip(raw)

    def get_active_trip_for_driver(self, driver_id: str) -> Optional[Dict[str, Any]]:
        raw = self.db.trips.find_one({
            "driver_id": driver_id,
            "state": {"$nin": ["COMPLETED", "CANCELLED"]}
        }, sort=[("created_at", DESCENDING)])
        return from_mongo_trip(raw)

    def list_trips_for_driver(self, driver_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.db.trips.find({"driver_id": driver_id}).sort("created_at", DESCENDING).limit(limit)
        return [from_mongo_trip(d) for d in cursor]

    def update_trip(self, trip_id: str, update_fields: Dict[str, Any]) -> bool:
        mongo_updates = to_mongo_trip(update_fields)
        res = self.db.trips.update_one(
            {"trip_id": trip_id},
            {"$set": mongo_updates}
        )
        return res.modified_count > 0 or res.matched_count > 0

    # ========================================================================
    # PASSENGER ACCESS TOKENS
    # ========================================================================

    def store_passenger_access(self, access_doc: Dict[str, Any]) -> None:
        self.db.trip_passenger_access.insert_one(access_doc)

    def get_passenger_access_by_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        raw = self.db.trip_passenger_access.find_one({"token_hash": token_hash})
        if raw and "_id" in raw:
            del raw["_id"]
        return raw

    def increment_access_count(self, token_hash: str, accessed_at: str) -> None:
        self.db.trip_passenger_access.update_one(
            {"token_hash": token_hash},
            {
                "$inc": {"access_count": 1},
                "$set": {"last_accessed_at": accessed_at}
            }
        )

    def revoke_passenger_access(self, trip_id: str) -> bool:
        res = self.db.trip_passenger_access.update_many(
            {"trip_id": trip_id},
            {"$set": {"is_revoked": True}}
        )
        return res.modified_count > 0

    # ========================================================================
    # TRIP EVENTS (AUDIT TRAIL)
    # ========================================================================

    def insert_event(self, event_doc: Dict[str, Any]) -> str:
        self.db.trip_events.insert_one(event_doc)
        return event_doc["event_id"]

    def list_events_for_trip(self, trip_id: str) -> List[Dict[str, Any]]:
        cursor = self.db.trip_events.find({"trip_id": trip_id}).sort("timestamp", ASCENDING)
        res = []
        for d in cursor:
            if "_id" in d:
                del d["_id"]
            res.append(d)
        return res

    # ========================================================================
    # TRIP PAYMENTS
    # ========================================================================

    def insert_payment(self, payment_doc: Dict[str, Any]) -> str:
        mongo_doc = to_mongo_trip(payment_doc)
        self.db.trip_payments.insert_one(mongo_doc)
        return payment_doc["payment_id"]

    def list_payments_for_trip(self, trip_id: str) -> List[Dict[str, Any]]:
        cursor = self.db.trip_payments.find({"trip_id": trip_id}).sort("collected_at", ASCENDING)
        return [from_mongo_trip(d) for d in cursor]
