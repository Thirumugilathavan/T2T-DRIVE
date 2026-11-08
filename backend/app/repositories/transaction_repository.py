"""
Append-Only Transaction Repository for T2T DRIVE.
Enforces the single source of truth for all financial transactions.
Never exposes update or delete methods on completed ledger records.
"""

from typing import List, Dict, Any, Optional
import bson
from decimal import Decimal
from pymongo import ASCENDING, DESCENDING
from app.models.financial import quantize_money, format_money


def to_mongo_doc(data: Dict[str, Any]) -> Dict[str, Any]:
    """Converts Python Decimals into MongoDB Decimal128 for database storage."""
    doc = dict(data)
    for k, v in doc.items():
        if isinstance(v, Decimal):
            doc[k] = bson.Decimal128(str(v))
        elif isinstance(v, dict):
            doc[k] = to_mongo_doc(v)
    return doc


def from_mongo_doc(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Converts MongoDB Decimal128 back into Python Decimal upon retrieval."""
    if data is None:
        return None
    doc = dict(data)
    if "_id" in doc:
        del doc["_id"]
    for k, v in doc.items():
        if isinstance(v, bson.Decimal128):
            doc[k] = v.to_decimal()
        elif isinstance(v, dict):
            doc[k] = from_mongo_doc(v)
    return doc


class TransactionRepository:
    """
    MongoDB repository for the append-only transactions collection.
    """

    def __init__(self, db):
        self.db = db

    def insert_transaction(self, txn_doc: Dict[str, Any]) -> str:
        """
        Appends a new financial transaction to the ledger.
        There is NO update_transaction or delete_transaction method.
        """
        mongo_doc = to_mongo_doc(txn_doc)
        self.db.transactions.insert_one(mongo_doc)
        return txn_doc["transaction_id"]

    def get_by_id(self, transaction_id: str, driver_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single transaction by ID, optionally scoped to driver for isolation.
        """
        query: Dict[str, Any] = {"transaction_id": transaction_id}
        if driver_id:
            query["driver_id"] = driver_id
        doc = self.db.transactions.find_one(query)
        return from_mongo_doc(doc)

    def find_transactions(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        categories: Optional[List[str]] = None,
        transaction_types: Optional[List[str]] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Finds paginated transactions matching driver and criteria.
        """
        query: Dict[str, Any] = {"driver_id": driver_id}
        if vehicle_id:
            query["vehicle_id"] = vehicle_id
        if start_date and end_date:
            query["transaction_date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["transaction_date"] = {"$gte": start_date}
        elif end_date:
            query["transaction_date"] = {"$lte": end_date}
        if categories:
            query["category"] = {"$in": categories}
        if transaction_types:
            query["transaction_type"] = {"$in": transaction_types}

        cursor = self.db.transactions.find(query).sort([
            ("transaction_date", DESCENDING),
            ("created_at", DESCENDING)
        ]).skip(skip).limit(limit)

        return [from_mongo_doc(doc) for doc in cursor if doc]

    def get_transactions_for_driver(self, driver_id: str) -> List[Dict[str, Any]]:
        """Convenience helper to retrieve all transactions for a driver."""
        return self.find_transactions(driver_id=driver_id, limit=1000)

    def count_transactions(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> int:
        """Counts matching transactions for pagination metadata."""
        query: Dict[str, Any] = {"driver_id": driver_id}
        if vehicle_id:
            query["vehicle_id"] = vehicle_id
        if start_date and end_date:
            query["transaction_date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["transaction_date"] = {"$gte": start_date}
        elif end_date:
            query["transaction_date"] = {"$lte": end_date}
        return self.db.transactions.count_documents(query)

    def find_active_reversal(self, original_transaction_id: str) -> Optional[Dict[str, Any]]:
        """Checks if a reversal transaction already exists for an original transaction."""
        doc = self.db.transactions.find_one({
            "reference_id": original_transaction_id,
            "transaction_type": {"$in": ["INCOME_REVERSAL", "EXPENSE_REVERSAL", "OWNER_PAYMENT_REVERSAL"]}
        })
        return from_mongo_doc(doc)
