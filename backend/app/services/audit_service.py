"""
Audit Logging Service for T2T DRIVE Financial Engine.
Provides an append-only audit trail for all financial state changes,
confirmations, cancellations, reversals, and security events.
"""

import logging
import secrets
from typing import Dict, Any, Optional, List
from app.utils.dates import now_utc

logger = logging.getLogger(__name__)


class AuditService:
    """
    Persists immutable audit events to the audit_logs collection.
    """

    def __init__(self, db):
        self.db = db

    def log_event(
        self,
        driver_id: str,
        event_type: Optional[str] = None,
        resource_type: str = "general",
        resource_id: str = "none",
        actor: str = "DRIVER",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Appends an audit log entry.
        Never stores passwords, tokens, OTPs, or cryptographic keys.
        """
        event_id = f"EVT_{secrets.token_hex(8)}"
        eff_event_type = event_type or kwargs.get("action") or "UNKNOWN_EVENT"
        eff_metadata = metadata if metadata is not None else kwargs.get("details", {})
        clean_metadata = self._sanitize_metadata(eff_metadata)

        doc = {
            "event_id": event_id,
            "driver_id": driver_id,
            "event_type": eff_event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": now_utc(),
            "actor": actor,
            "metadata": clean_metadata
        }

        try:
            self.db.audit_logs.insert_one(doc)
            logger.info(
                "Audit log recorded: [%s] %s on %s:%s by %s",
                event_id, event_type, resource_type, resource_id, actor
            )
        except Exception as err:
            logger.error("Failed to write audit log event: %s", err)

        return event_id

    def list_driver_audit_logs(
        self,
        driver_id: str,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Retrieves paginated audit log entries for an authenticated driver.
        """
        cursor = self.db.audit_logs.find(
            {"driver_id": driver_id},
            {"_id": 0}
        ).sort("timestamp", -1).skip(skip).limit(limit)

        results = []
        for doc in cursor:
            # Ensure timestamps are ISO formatted strings for API response
            if "timestamp" in doc and hasattr(doc["timestamp"], "isoformat"):
                doc["timestamp"] = doc["timestamp"].isoformat()
            results.append(doc)
        return results

    @staticmethod
    def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
        """Strips any sensitive credentials that might accidentally be passed."""
        forbidden_keys = {"token", "jwt", "otp", "password", "secret", "authorization"}
        sanitized = {}
        for k, v in meta.items():
            if k.lower() in forbidden_keys:
                continue
            # Convert non-serializable objects
            if hasattr(v, "isoformat"):
                sanitized[k] = v.isoformat()
            elif hasattr(v, "to_decimal"):
                sanitized[k] = str(v.to_decimal())
            else:
                sanitized[k] = str(v) if isinstance(v, (int, float, str, bool, list, dict)) else str(v)
        return sanitized
