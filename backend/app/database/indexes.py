"""
MongoDB Index Initialization for T2T DRIVE.
Defines unique constraints, user-level isolation indexes, query optimization indexes,
and TTL indexes across all financial collections.
"""

import logging
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


def ensure_indexes(db):
    """
    Creates and verifies all MongoDB indexes required for T2T DRIVE.
    Ensures user-level isolation, query performance, and unique constraints.
    """
    if db is None:
        logger.warning("Database not initialized. Skipping index creation.")
        return

    try:
        # 1. drivers Collection
        db.drivers.create_index([("driver_id", ASCENDING)], unique=True)
        db.drivers.create_index([("phone", ASCENDING)], unique=True)

        # 2. vehicles Collection
        db.vehicles.create_index([("vehicle_id", ASCENDING)], unique=True)
        db.vehicles.create_index([("registration_number", ASCENDING)], unique=True)
        db.vehicles.create_index([("assigned_driver_ids", ASCENDING)])

        # 3. otp_verifications Collection (Auth OTP storage & rate limiting)
        db.otp_verifications.create_index([("phone", ASCENDING)])
        db.otp_verifications.create_index([("created_at", ASCENDING)], expireAfterSeconds=86400)  # 24h retention

        # 4. idempotency_records Collection
        db.idempotency_records.create_index(
            [("driver_id", ASCENDING), ("idempotency_key", ASCENDING), ("operation_type", ASCENDING)],
            unique=True
        )
        db.idempotency_records.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)  # 48h TTL

        # 5. pending_actions Collection (Preserved Audit - No hard delete TTL)
        db.pending_actions.create_index([("pending_action_id", ASCENDING)], unique=True)
        db.pending_actions.create_index([("driver_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])
        db.pending_actions.create_index([("driver_id", ASCENDING), ("idempotency_key", ASCENDING)])

        # 6. transactions Collection (Immutable Ledger)
        db.transactions.create_index([("transaction_id", ASCENDING)], unique=True)
        db.transactions.create_index([("driver_id", ASCENDING), ("transaction_date", DESCENDING)])
        db.transactions.create_index([("driver_id", ASCENDING), ("vehicle_id", ASCENDING), ("transaction_date", DESCENDING)])
        db.transactions.create_index([("driver_id", ASCENDING), ("idempotency_key", ASCENDING)], unique=True, sparse=True)
        db.transactions.create_index([("reference_id", ASCENDING)], sparse=True)

        # 7. settlements Collection (Multi-Shift, Multi-Vehicle, Versioned Audit)
        db.settlements.create_index([("settlement_id", ASCENDING)], unique=True)
        db.settlements.create_index(
            [("driver_id", ASCENDING), ("vehicle_id", ASCENDING), ("settlement_date", ASCENDING), ("shift_id", ASCENDING), ("version", DESCENDING)],
            unique=True
        )
        db.settlements.create_index([("driver_id", ASCENDING), ("settlement_date", DESCENDING)])

        # 8. documents Collection
        db.documents.create_index([("driver_id", ASCENDING), ("document_type", ASCENDING), ("vehicle_id", ASCENDING)], unique=True)
        db.documents.create_index([("expiry_date", ASCENDING)])

        # 9. reminders Collection
        db.reminders.create_index([("driver_id", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)])

        # 10. maintenance_records Collection
        db.maintenance_records.create_index([("vehicle_id", ASCENDING), ("service_date", DESCENDING)])
        db.maintenance_records.create_index([("driver_id", ASCENDING), ("service_date", DESCENDING)])

        # 11. conversation_sessions & messages
        db.conversation_sessions.create_index([("session_id", ASCENDING)], unique=True)
        db.conversation_sessions.create_index([("driver_id", ASCENDING), ("is_active", ASCENDING)])
        db.conversation_messages.create_index([("session_id", ASCENDING), ("timestamp", ASCENDING)])

        # 12. audit_logs Collection (Immutable Append-Only Audit Trail)
        db.audit_logs.create_index([("driver_id", ASCENDING), ("timestamp", DESCENDING)])
        db.audit_logs.create_index([("resource_type", ASCENDING), ("resource_id", ASCENDING)])

        # 13. revoked_tokens Collection (Server-side JWT session revocation with TTL cleanup)
        db.revoked_tokens.create_index([("jti", ASCENDING)], unique=True)
        db.revoked_tokens.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)

        logger.info("Successfully ensured all database indexes across 13 collections.")
    except Exception as err:
        logger.warning("Index creation notice (e.g. mongomock partial index support): %s", err)
