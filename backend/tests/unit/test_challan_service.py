"""
Unit Tests for ChallanService and Challan Domain Models.
Verifies challan creation, payment settlement, status transitions, OCR preview,
and cross-driver isolation.
"""

import pytest
import mongomock
import tempfile
import shutil
from decimal import Decimal

from app.models.challan import Challan, ChallanStatus
from app.repositories.challan_repository import ChallanRepository
from app.services.challan_service import ChallanService, MockOCRAdapter
from app.utils.storage import LocalStorageAdapter


@pytest.fixture
def challan_fixture():
    db = mongomock.MongoClient().t2t_drive_test
    d = tempfile.mkdtemp(prefix="t2t_chln_test_")
    storage = LocalStorageAdapter(base_directory=d, max_size_mb=5)
    repo = ChallanRepository(db=db)
    ocr = MockOCRAdapter()
    svc = ChallanService(db=db, challan_repo=repo, storage=storage, ocr_adapter=ocr)
    yield svc, repo, storage
    shutil.rmtree(d, ignore_errors=True)


def test_add_challan(challan_fixture):
    svc, repo, _ = challan_fixture

    res = svc.add_challan(
        driver_id="DRV_CHLN_1",
        challan_number="TN09A123456",
        vehicle_id="TN-09-CB-1284",
        registration_number="TN-09-CB-1284",
        violation_description="Red light jump",
        fine_amount=Decimal("500.00")
    )

    assert res["challan_id"].startswith("CHLN_")
    assert res["payment_status"] == ChallanStatus.UNPAID.value
    assert res["fine_amount"] == "500.00"


def test_record_challan_payment(challan_fixture):
    svc, repo, _ = challan_fixture

    c = svc.add_challan(
        driver_id="DRV_PAY",
        challan_number="TN09PAY123",
        vehicle_id="TN-09-CB-1284",
        registration_number="TN-09-CB-1284",
        violation_description="No parking",
        fine_amount=Decimal("200.00")
    )
    chln_id = c["challan_id"]

    paid = svc.record_payment(
        challan_id=chln_id,
        driver_id="DRV_PAY",
        payment_date="2026-11-08",
        payment_reference="UPI/20261108/998271"
    )

    assert paid["payment_status"] == ChallanStatus.PAID.value
    assert paid["payment_reference"] == "UPI/20261108/998271"


def test_invalid_challan_transition(challan_fixture):
    svc, repo, _ = challan_fixture

    c = svc.add_challan(
        driver_id="DRV_TRANS",
        challan_number="TN09TRANS99",
        vehicle_id="TN-09-CB-1284",
        registration_number="TN-09-CB-1284",
        violation_description="Over speeding",
        fine_amount=Decimal("1000.00")
    )
    chln_id = c["challan_id"]

    # Mark as PAID
    svc.record_payment(chln_id, "DRV_TRANS", "2026-11-08", "REF123")

    # Cannot transition PAID back to UNPAID
    with pytest.raises(ValueError, match="Invalid status transition"):
        svc.update_status(chln_id, "DRV_TRANS", "UNPAID")


def test_ocr_preview_untrusted_flag(challan_fixture):
    svc, repo, storage = challan_fixture
    fake_doc = b"%PDF-1.4\nNotice of Challan fine: 500"

    preview = svc.extract_from_upload(file_bytes=fake_doc, filename="notice.pdf")

    assert preview["needs_user_confirmation"] is True
    assert "ocr_disclaimer" in preview
    assert preview["challan_number"]
    assert preview["fine_amount"] == "500.00"


def test_cross_driver_challan_isolation(challan_fixture):
    svc, repo, _ = challan_fixture

    c = svc.add_challan(
        driver_id="DRV_OWNER_1",
        challan_number="CHLN_SEC_1",
        vehicle_id="TN-09-CB-1284",
        registration_number="TN-09-CB-1284",
        violation_description="Test violation",
        fine_amount=Decimal("100.00")
    )
    chln_id = c["challan_id"]

    with pytest.raises(PermissionError, match="You do not own this challan"):
        svc.get_challan(chln_id, "DRV_ATTACKER")
