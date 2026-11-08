"""
Optional Live MongoDB Integration Tests.
Executes only when a valid real MongoDB server URI is explicitly provided
via the environment variable TEST_LIVE_MONGODB_URI.
Never runs in standard mock-only environments.
"""

import os
import pytest
from decimal import Decimal
from pymongo import MongoClient
from app.models.financial import TransactionType
from app.repositories.transaction_repository import TransactionRepository, to_mongo_doc, from_mongo_doc


LIVE_URI = os.getenv("TEST_LIVE_MONGODB_URI")


@pytest.mark.skipif(not LIVE_URI, reason="TEST_LIVE_MONGODB_URI not set. Skipped in in-memory mongomock environment.")
def test_real_mongodb_decimal128_round_trip():
    client = MongoClient(LIVE_URI, serverSelectionTimeoutMS=2000)
    db = client["t2t_drive_integration_test"]
    try:
        repo = TransactionRepository(db)
        doc = {
            "transaction_id": "TXN_LIVE_1",
            "driver_id": "DRV_LIVE",
            "vehicle_id": "KA01LIVE",
            "transaction_type": "INCOME",
            "amount": Decimal("1500.50"),
            "signed_amount": Decimal("1500.50"),
            "category": "FARE"
        }
        repo.insert_transaction(doc)
        read_back = repo.get_by_id("TXN_LIVE_1", "DRV_LIVE")
        assert read_back is not None
        assert read_back["amount"] == Decimal("1500.50")
    finally:
        db.transactions.delete_many({"driver_id": "DRV_LIVE"})
        client.close()
