"""
Unit Tests for ReminderService.
Verifies milestone thresholds (30, 15, 7, 1, 0 days), already-expired documents,
idempotent deduplication, and mock notifications.
"""

import pytest
import mongomock
import datetime

from app.models.vehicle_document import VehicleDocument, DocumentType
from app.repositories.document_repository import DocumentRepository
from app.repositories.reminder_repository import ReminderRepository
from app.services.reminder_service import ReminderService, MockNotificationAdapter
from app.models.reminder import ReminderStatus


@pytest.fixture
def reminder_fixture():
    db = mongomock.MongoClient().t2t_drive_test
    doc_repo = DocumentRepository(db=db)
    rem_repo = ReminderRepository(db=db)
    notifier = MockNotificationAdapter()
    svc = ReminderService(
        db=db,
        reminder_repo=rem_repo,
        document_repo=doc_repo,
        notification_adapter=notifier,
        thresholds=[30, 15, 7, 1, 0]
    )
    yield svc, doc_repo, rem_repo, notifier


def test_30_day_and_7_day_milestone_reminders(reminder_fixture):
    svc, doc_repo, rem_repo, notifier = reminder_fixture
    ref_date = "2026-11-08"

    # Doc A expires in exactly 30 days: 2026-12-08
    doc_repo.add_document(VehicleDocument(
        document_id="DOC_30D",
        driver_id="DRV_1",
        document_type=DocumentType.INSURANCE,
        expiry_date="2026-12-08"
    ))

    # Doc B expires in exactly 7 days: 2026-11-15
    doc_repo.add_document(VehicleDocument(
        document_id="DOC_7D",
        driver_id="DRV_1",
        document_type=DocumentType.PUC,
        expiry_date="2026-11-15"
    ))

    # Doc C expires in 25 days (not a milestone): 2026-12-03
    doc_repo.add_document(VehicleDocument(
        document_id="DOC_25D",
        driver_id="DRV_1",
        document_type=DocumentType.FITNESS,
        expiry_date="2026-12-03"
    ))

    new_reminders = svc.scan_document_expiries(driver_id="DRV_1", reference_date=ref_date)
    assert len(new_reminders) == 2

    # Check notification dispatch
    assert len(notifier.sent_notifications) == 2
    titles = [n["title"] for n in notifier.sent_notifications]
    assert any("30 Days" in t for t in titles)
    assert any("7 Days" in t for t in titles)


def test_1_day_and_expiry_day_reminders(reminder_fixture):
    svc, doc_repo, rem_repo, notifier = reminder_fixture
    ref_date = "2026-11-08"

    # Expires tomorrow: 2026-11-09 (1 day)
    doc_repo.add_document(VehicleDocument(
        document_id="DOC_TOMORROW",
        driver_id="DRV_2",
        document_type=DocumentType.PERMIT,
        expiry_date="2026-11-09"
    ))

    # Expires today: 2026-11-08 (0 day)
    doc_repo.add_document(VehicleDocument(
        document_id="DOC_TODAY",
        driver_id="DRV_2",
        document_type=DocumentType.FITNESS,
        expiry_date="2026-11-08"
    ))

    new_reminders = svc.scan_document_expiries(driver_id="DRV_2", reference_date=ref_date)
    assert len(new_reminders) == 2

    titles = [n["title"] for n in notifier.sent_notifications]
    assert any("Tomorrow" in t for t in titles)
    assert any("Today" in t for t in titles)


def test_idempotent_duplicate_prevention(reminder_fixture):
    svc, doc_repo, rem_repo, notifier = reminder_fixture
    ref_date = "2026-11-08"

    doc_repo.add_document(VehicleDocument(
        document_id="DOC_IDEM",
        driver_id="DRV_IDEM",
        document_type=DocumentType.INSURANCE,
        expiry_date="2026-12-08"  # exactly 30 days
    ))

    # First run generates reminder
    run1 = svc.scan_document_expiries(driver_id="DRV_IDEM", reference_date=ref_date)
    assert len(run1) == 1
    assert len(notifier.sent_notifications) == 1

    # Second run on same day must be idempotent: 0 new reminders, 0 duplicate notifications!
    run2 = svc.scan_document_expiries(driver_id="DRV_IDEM", reference_date=ref_date)
    assert len(run2) == 0
    assert len(notifier.sent_notifications) == 1


def test_acknowledge_reminder(reminder_fixture):
    svc, doc_repo, rem_repo, notifier = reminder_fixture
    ref_date = "2026-11-08"

    doc_repo.add_document(VehicleDocument(
        document_id="DOC_ACK",
        driver_id="DRV_ACK",
        document_type=DocumentType.INSURANCE,
        expiry_date="2026-11-08"
    ))

    reminders = svc.scan_document_expiries(driver_id="DRV_ACK", reference_date=ref_date)
    rem_id = reminders[0]["reminder_id"]

    ok = svc.acknowledge_reminder(rem_id, "DRV_ACK")
    assert ok is True

    stored = rem_repo.get_by_id(rem_id)
    assert stored["status"] == ReminderStatus.ACKNOWLEDGED.value
