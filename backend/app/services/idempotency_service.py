"""
Idempotency Engine for T2T DRIVE Financial Operations.
Guarantees at-most-once execution for all financial requests, prevents double-clicks,
and securely handles retries across network or voice disconnects.
"""

import json
import hashlib
import datetime
import logging
from typing import Dict, Any, Optional, Tuple
from pymongo.errors import DuplicateKeyError
from app.utils.dates import now_utc

logger = logging.getLogger(__name__)


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request payload."""
    pass


class OperationInProgressError(Exception):
    """Raised when an identical request is already being processed concurrently."""
    pass


def canonical_hash(data: Any) -> str:
    """
    Produces a deterministic SHA-256 hash of a payload by recursively
    sorting keys and formatting types consistently.
    """
    def _normalize(obj):
        if isinstance(obj, dict):
            return {str(k): _normalize(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, (list, tuple)):
            return [_normalize(item) for item in obj]
        elif hasattr(obj, "to_decimal"):
            return str(obj.to_decimal())
        elif hasattr(obj, "isoformat"):
            return obj.isoformat()
        else:
            return str(obj)

    normalized = _normalize(data)
    canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class IdempotencyService:
    """
    Manages client-generated idempotency keys in MongoDB.
    """

    def __init__(self, db, audit_service=None):
        self.db = db
        self.audit_service = audit_service

    def start_operation(
        self,
        driver_id: str,
        idempotency_key: str,
        operation_type: str,
        payload: Any
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Attempts to acquire the idempotency key lock.

        Returns:
            (is_cached, cached_response)
            - If (True, response_data): Request was previously completed; return cached response immediately.
            - If (False, None): Key acquired; proceed to execute operation.

        Raises:
            IdempotencyConflictError: If key was previously used with a different payload.
            OperationInProgressError: If key is currently being processed by a concurrent thread.
        """
        if not idempotency_key or not driver_id:
            raise ValueError("Both driver_id and idempotency_key are required for idempotency.")

        req_hash = canonical_hash(payload)
        now = now_utc()
        expires_at = now + datetime.timedelta(hours=48)

        # 1. Check for existing record
        existing = self.db.idempotency_records.find_one({
            "driver_id": driver_id,
            "idempotency_key": idempotency_key,
            "operation_type": operation_type
        })

        if existing:
            # Check payload integrity
            if existing.get("request_hash") != req_hash:
                logger.warning(
                    "Idempotency conflict: Key %s reused with different payload by driver %s",
                    idempotency_key, driver_id
                )
                raise IdempotencyConflictError(
                    f"Idempotency key '{idempotency_key}' was previously used with a different request payload."
                )

            status = existing.get("status")
            if status == "COMPLETED":
                logger.info(
                    "Idempotent replay detected: Returning cached result for key %s",
                    idempotency_key
                )
                if self.audit_service:
                    self.audit_service.log_event(
                        driver_id=driver_id,
                        event_type="IDEMPOTENT_RETRY",
                        resource_type="IDEMPOTENCY",
                        resource_id=idempotency_key,
                        metadata={"operation_type": operation_type}
                    )
                return True, existing.get("response_data")

            elif status == "IN_PROGRESS":
                created_at = existing.get("created_at")
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=datetime.timezone.utc)
                age_seconds = (now - created_at).total_seconds() if created_at else 0
                if age_seconds > 60:
                    logger.warning(
                        "Recovering abandoned IN_PROGRESS operation for key %s (age %.1fs)",
                        idempotency_key, age_seconds
                    )
                    self.db.idempotency_records.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {"status": "IN_PROGRESS", "created_at": now, "expires_at": expires_at}}
                    )
                    return False, None

                raise OperationInProgressError(
                    f"Operation with idempotency key '{idempotency_key}' is already in progress. Please wait."
                )

            elif status == "FAILED":
                # Previous attempt failed; permit retry by resetting to IN_PROGRESS
                self.db.idempotency_records.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"status": "IN_PROGRESS", "created_at": now, "expires_at": expires_at}}
                )
                return False, None

        # 2. Try to insert new IN_PROGRESS record atomically
        record = {
            "driver_id": driver_id,
            "idempotency_key": idempotency_key,
            "operation_type": operation_type,
            "request_hash": req_hash,
            "resource_id": None,
            "status": "IN_PROGRESS",
            "response_data": None,
            "created_at": now,
            "completed_at": None,
            "expires_at": expires_at
        }

        try:
            self.db.idempotency_records.insert_one(record)
            return False, None
        except DuplicateKeyError:
            # Concurrent race condition: another thread just inserted it
            return self.start_operation(driver_id, idempotency_key, operation_type, payload)

    def complete_operation(
        self,
        driver_id: str,
        idempotency_key: str,
        operation_type: str,
        resource_id: str,
        response_data: Dict[str, Any]
    ) -> None:
        """
        Marks an operation as COMPLETED and stores the response envelope for safe idempotent replay.
        """
        now = now_utc()
        self.db.idempotency_records.update_one(
            {
                "driver_id": driver_id,
                "idempotency_key": idempotency_key,
                "operation_type": operation_type
            },
            {
                "$set": {
                    "status": "COMPLETED",
                    "resource_id": resource_id,
                    "response_data": response_data,
                    "completed_at": now
                }
            }
        )

    def fail_operation(
        self,
        driver_id: str,
        idempotency_key: str,
        operation_type: str,
        error_message: str
    ) -> None:
        """
        Marks an operation as FAILED so that subsequent retries are permitted.
        """
        self.db.idempotency_records.update_one(
            {
                "driver_id": driver_id,
                "idempotency_key": idempotency_key,
                "operation_type": operation_type
            },
            {
                "$set": {
                    "status": "FAILED",
                    "error_message": error_message,
                    "completed_at": now_utc()
                }
            }
        )
