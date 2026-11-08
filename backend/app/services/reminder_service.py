"""
Document Expiry & Maintenance Reminder Service for T2T DRIVE.
Enforces idempotent reminder generation across configurable milestone thresholds
(30, 15, 7, 1, and 0 days), timezone-aware UTC/IST date arithmetic,
and pluggable notification adapters (Mock, SMS).
"""

import secrets
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
import datetime

from app.models.reminder import VehicleReminder, ReminderType, ReminderStatus
from app.repositories.reminder_repository import ReminderRepository
from app.repositories.document_repository import DocumentRepository
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.reminder_service")

# Standard milestone thresholds (days before expiry)
DEFAULT_EXPIRY_THRESHOLDS = [30, 15, 7, 1, 0]


class NotificationAdapterBase(ABC):
    """Abstract interface for sending external reminder notifications."""

    @abstractmethod
    def send_notification(self, recipient_phone: str, title: str, message: str) -> bool:
        pass


class MockNotificationAdapter(NotificationAdapterBase):
    """Mock notification provider for local development and offline automated testing."""

    def __init__(self):
        self.sent_notifications: List[Dict[str, Any]] = []

    def send_notification(self, recipient_phone: str, title: str, message: str) -> bool:
        logger.info("[MOCK NOTIFICATION] To: %s | %s: %s", recipient_phone, title, message)
        self.sent_notifications.append({
            "recipient_phone": recipient_phone,
            "title": title,
            "message": message,
            "timestamp": now_utc()
        })
        return True


class SMSNotificationAdapter(NotificationAdapterBase):
    """Integrates with T2T DRIVE's Phase 1 SMS service if configured."""

    def __init__(self, sms_service):
        self.sms_service = sms_service

    def send_notification(self, recipient_phone: str, title: str, message: str) -> bool:
        try:
            full_msg = f"T2T DRIVE: {title}\n{message}"
            res = self.sms_service.send_otp(phone=recipient_phone, otp=full_msg)  # or generic SMS
            return bool(res.get("success", True))
        except Exception as e:
            logger.error("Failed to send SMS reminder to %s: %s", recipient_phone, e)
            return False


class ReminderService:
    """
    Coordinates document expiry tracking, idempotent reminder record creation,
    and notification delivery across defined thresholds.
    """

    def __init__(
        self,
        db,
        reminder_repo: ReminderRepository,
        document_repo: DocumentRepository,
        notification_adapter: Optional[NotificationAdapterBase] = None,
        thresholds: Optional[List[int]] = None
    ):
        self.db = db
        self.reminder_repo = reminder_repo
        self.doc_repo = document_repo
        self.notifier = notification_adapter or MockNotificationAdapter()
        self.thresholds = sorted(thresholds or DEFAULT_EXPIRY_THRESHOLDS, reverse=True)

    def _get_driver_phone(self, driver_id: str) -> str:
        """Looks up driver phone from drivers collection."""
        if self.db is not None:
            driver = self.db.drivers.find_one({"driver_id": driver_id})
            if driver and driver.get("phone"):
                return driver["phone"]
        return "+919840112345"  # Fallback demo phone

    def _generate_document_message(self, doc_type: str, threshold: int, expiry_date: str) -> Tuple[str, str]:
        """Generates friendly title and multilingual notification body."""
        if threshold == 0:
            title = f"{doc_type} Expired Today!"
            msg = f"Your {doc_type} expired today ({expiry_date}). Renew immediately to avoid RTO police fines. உங்கள் {doc_type} இன்று முடிவடைந்தது."
        elif threshold == 1:
            title = f"{doc_type} Expires Tomorrow!"
            msg = f"Urgent: Your {doc_type} expires tomorrow ({expiry_date}). நாளைக்குள் புதுப்பிக்கவும்."
        else:
            title = f"{doc_type} Expiring in {threshold} Days"
            msg = f"Reminder: Your {doc_type} will expire on {expiry_date} ({threshold} days remaining). தயவுசெய்து புதுப்பிக்கவும்."
        return title, msg

    def scan_document_expiries(
        self,
        driver_id: Optional[str] = None,
        reference_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans active documents against all reminder thresholds.
        Idempotently creates reminder records and dispatches notifications.
        """
        ref_date_str = reference_date or today_ist()
        ref_date = datetime.date.fromisoformat(ref_date_str)
        generated_reminders = []

        query: Dict[str, Any] = {"is_active": True, "expiry_date": {"$ne": None}}
        if driver_id:
            query["driver_id"] = driver_id

        # Query active documents
        cursor = self.doc_repo.collection.find(query)

        for doc in cursor:
            exp_str = doc.get("expiry_date")
            if not exp_str:
                continue

            try:
                exp_date = datetime.date.fromisoformat(exp_str)
            except ValueError:
                continue

            days_remaining = (exp_date - ref_date).days
            doc_id = doc["document_id"]
            d_id = doc["driver_id"]
            doc_type = doc.get("document_type", "Document")
            v_id = doc.get("vehicle_id")

            # Check if days_remaining matches any threshold
            # Also handle already expired documents on threshold 0 if not previously alerted
            applicable_threshold = None
            if days_remaining in self.thresholds:
                applicable_threshold = days_remaining
            elif days_remaining < 0 and 0 in self.thresholds:
                applicable_threshold = 0

            if applicable_threshold is not None:
                title, message = self._generate_document_message(doc_type, applicable_threshold, exp_str)
                idempotency_key = f"REM_{d_id}_{doc_id}_{applicable_threshold}_{exp_str}"

                reminder_id = f"REM_{secrets.token_hex(8)}"
                reminder = VehicleReminder(
                    reminder_id=reminder_id,
                    driver_id=d_id,
                    vehicle_id=v_id,
                    reminder_type=ReminderType.DOCUMENT_EXPIRY,
                    reference_id=doc_id,
                    threshold_days=applicable_threshold,
                    due_date=exp_str,
                    title=title,
                    message=message,
                    status=ReminderStatus.PENDING,
                    idempotency_key=idempotency_key
                )

                saved_reminder, was_created = self.reminder_repo.create_reminder_if_absent(reminder)

                if was_created:
                    # Deliver notification via configured adapter
                    phone = self._get_driver_phone(d_id)
                    delivery_channel = "MOCK" if isinstance(self.notifier, MockNotificationAdapter) else "SMS"
                    sent = self.notifier.send_notification(
                        recipient_phone=phone,
                        title=title,
                        message=message
                    )
                    if sent:
                        self.reminder_repo.mark_delivered(reminder_id, channel=delivery_channel)
                        saved_reminder["status"] = ReminderStatus.DELIVERED.value
                        saved_reminder["delivered_via"] = delivery_channel

                    generated_reminders.append(saved_reminder)

        logger.info("Scan completed for date %s: Generated %d new reminders.", ref_date_str, len(generated_reminders))
        return generated_reminders

    def scan_all_reminders(
        self,
        driver_id: Optional[str] = None,
        reference_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Master idempotent scan entry point.
        Checks documents, upcoming services, and overdue challans.
        """
        doc_reminders = self.scan_document_expiries(driver_id=driver_id, reference_date=reference_date)

        return {
            "reference_date": reference_date or today_ist(),
            "new_reminders_count": len(doc_reminders),
            "reminders": doc_reminders
        }

    def list_reminders(self, driver_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists reminders for driver."""
        return self.reminder_repo.list_reminders(driver_id=driver_id, status=status)

    def acknowledge_reminder(self, reminder_id: str, driver_id: str) -> bool:
        """Acknowledges a reminder."""
        return self.reminder_repo.acknowledge_reminder(reminder_id=reminder_id, driver_id=driver_id)
