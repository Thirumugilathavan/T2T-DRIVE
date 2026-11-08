"""
Unit Tests for VehicleDocument and DocumentService.
Verifies document creation, expiry status calculations, renewals/superseding,
and cross-driver security isolation.
"""

import pytest
import mongomock
import tempfile
import shutil

from app.models.vehicle_document import VehicleDocument, DocumentType, ExpiryStatus, normalize_document_type
from app.repositories.document_repository import DocumentRepository
from app.repositories.reminder_repository import ReminderRepository
from app.services.document_service import DocumentService, mask_document_number
from app.utils.storage import LocalStorageAdapter


@pytest.fixture
def test_setup():
    db = mongomock.MongoClient().t2t_drive_test
    d = tempfile.mkdtemp(prefix="t2t_doc_test_")
    storage = LocalStorageAdapter(base_directory=d, max_size_mb=5)
    doc_repo = DocumentRepository(db=db)
    rem_repo = ReminderRepository(db=db)
    svc = DocumentService(db=db, document_repo=doc_repo, storage=storage, reminder_repo=rem_repo)
    yield svc, db
    shutil.rmtree(d, ignore_errors=True)


def test_document_type_normalization():
    assert normalize_document_type("Driving Licence (DL)") == DocumentType.DRIVING_LICENCE
    assert normalize_document_type("Vehicle Insurance") == DocumentType.INSURANCE
    assert normalize_document_type("PUC Certificate") == DocumentType.PUC
    assert normalize_document_type("Fitness Certificate (FC)") == DocumentType.FITNESS
    assert normalize_document_type("Registration Certificate (RC)") == DocumentType.RC


def test_document_number_masking():
    assert mask_document_number(None) is None
    assert mask_document_number("123") == "123"
    assert mask_document_number("TN091234") == "TN****34"
    assert mask_document_number("TN-09-2018-004821") == "TN-0****4821"


def test_expiry_status_calculations():
    doc_active = VehicleDocument(
        document_id="DOC_1",
        driver_id="DRV_1",
        document_type=DocumentType.INSURANCE,
        expiry_date="2026-12-15"
    )
    status, days = doc_active.calculate_expiry_status(reference_date="2026-11-08")
    assert status == ExpiryStatus.ACTIVE
    assert days == 37

    doc_expiring_soon = VehicleDocument(
        document_id="DOC_2",
        driver_id="DRV_1",
        document_type=DocumentType.PUC,
        expiry_date="2026-11-20"
    )
    status_soon, days_soon = doc_expiring_soon.calculate_expiry_status(reference_date="2026-11-08")
    assert status_soon == ExpiryStatus.EXPIRING_SOON
    assert days_soon == 12

    doc_expired = VehicleDocument(
        document_id="DOC_3",
        driver_id="DRV_1",
        document_type=DocumentType.FITNESS,
        expiry_date="2026-11-01"
    )
    status_exp, days_exp = doc_expired.calculate_expiry_status(reference_date="2026-11-08")
    assert status_exp == ExpiryStatus.EXPIRED
    assert days_exp == -7


def test_document_add_and_supersede(test_setup):
    svc, db = test_setup

    # Register initial insurance
    doc1 = svc.add_document(
        driver_id="DRV_A",
        document_type_str="Vehicle Insurance",
        document_number="POL-111",
        expiry_date="2026-11-15",
        vehicle_id="TN-09-CB-1284"
    )
    assert doc1["document_id"].startswith("DOC_")
    assert doc1["is_active"] is True

    # Renew insurance with new policy
    doc2 = svc.add_document(
        driver_id="DRV_A",
        document_type_str="Vehicle Insurance",
        document_number="POL-222",
        expiry_date="2027-11-15",
        vehicle_id="TN-09-CB-1284"
    )
    assert doc2["document_id"] != doc1["document_id"]

    # Verify old doc was superseded
    old_doc = svc.repo.get_by_id(doc1["document_id"])
    assert old_doc["is_active"] is False
    assert old_doc["superseded_by"] == doc2["document_id"]
    assert old_doc["verification_status"] == "SUPERSEDED"


def test_cross_driver_document_isolation(test_setup):
    svc, db = test_setup

    doc = svc.add_document(
        driver_id="DRV_ALICE",
        document_type_str="Driving Licence",
        document_number="DL-ALICE-123",
        expiry_date="2030-01-01"
    )
    doc_id = doc["document_id"]

    # Alice can view
    alice_view = svc.get_document(doc_id, "DRV_ALICE")
    assert alice_view["document_id"] == doc_id

    # Bob is rejected
    with pytest.raises(PermissionError, match="You do not own this document"):
        svc.get_document(doc_id, "DRV_BOB")


def test_compliance_status_summary(test_setup):
    svc, db = test_setup

    # Add 1 active, 1 warning (15 days), 1 critical (3 days)
    svc.add_document(driver_id="DRV_FLEET", document_type_str="RC", expiry_date="2028-01-01")
    svc.add_document(driver_id="DRV_FLEET", document_type_str="PUC", expiry_date="2026-11-20")

    summary = svc.get_compliance_status("DRV_FLEET")
    assert summary["total_documents"] == 2
    assert summary["active_count"] >= 1
