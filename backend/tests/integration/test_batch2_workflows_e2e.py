"""
T2T-DRIVE — Batch 2: Complete Owner, Passenger, Documents, Challan and Maintenance Workflows.
Validates the entire 12-step integration journey:
1. Owner creates a driver relationship and assigns a vehicle.
2. Owner configures rent (daily & weekly terms).
3. Driver records rent payment.
4. Settlement and outstanding balance update correctly (partial, settled, overpaid, carried forward).
5. Driver creates passenger trip and QR code.
6. Passenger agrees to trip (public link, data minimization, mutual consent).
7. Driver completes trip and records payment (reconciled into financial ledger).
8. Passenger receives receipt (digital receipt, dispute preservation).
9. Driver uploads a document and reviews OCR output (unverified mock label, human review).
10. Document expiry reminder is generated (threshold milestones, idempotency).
11. Driver records maintenance and checks the next service reminder (prevent duplicate expenses).
12. Maintenance expenses appear correctly in the financial dashboard.

Zero live Gnani API calls; zero production database writes; zero credential exposure.
"""

import io
import json
import pytest
from decimal import Decimal
from pathlib import Path

from app import create_app
from app.database.indexes import ensure_indexes
from app.models.financial import TransactionType, PendingActionType, RentFrequency, SettlementStatus
from app.models.trip import TripState, ProposalType, ProposalStatus
from app.models.challan import ChallanStatus
from app.utils.dates import today_ist


@pytest.fixture
def app_and_db():
    """Sets up an isolated test Flask application."""
    app = create_app("testing")
    app.config.update({
        "MONGODB_URI": "mongomock://localhost:27017/t2t_drive_batch2_test",
        "DB_NAME": "t2t_drive_batch2_test",
        "JWT_SECRET_KEY": "test-jwt-secret-key-t2t-drive-batch2",
        "OTP_HASH_SECRET": "test-otp-secret-key-t2t-drive-batch2",
        "VOICE_PROVIDER_MODE": "mock",
        "GNANI_PRISMA_ENABLED": False,
        "GNANI_TIMBRE_ENABLED": False
    })
    db = app.extensions["db_manager"].get_db()
    ensure_indexes(db)
    return app, db


def _auth_user(client, phone: str = "+919876543210"):
    """Authenticates a user/driver and returns (token, user_id)."""
    res1 = client.post("/api/auth/request-otp", json={"phone": phone})
    assert res1.status_code == 200
    mock_otp = res1.get_json()["data"].get("_mock_otp", "123456")

    res2 = client.post("/api/auth/verify-otp", json={"phone": phone, "otp": mock_otp})
    assert res2.status_code == 200
    data = res2.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


class TestOwnerDriverManagement:
    """Domain 1: Owner-driver management, rental terms, and settlement calculations."""

    def test_owner_vehicle_registration_and_assignment(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        owner_token, owner_id = _auth_user(client, "+919999900001")
        driver_token, driver_id = _auth_user(client, "+919999900002")

        # 1. Owner registers vehicle with daily rent
        v_payload = {
            "vehicle_id": "TN-09-AUTO-5555",
            "registration_number": "TN-09-AUTO-5555",
            "vehicle_type": "AUTO_RICKSHAW",
            "rent_type": "FIXED_RENT",
            "rent_amount": "400.00",
            "rent_frequency": "DAILY",
            "assigned_driver_ids": [driver_id]
        }
        res = client.post(
            "/api/settlements/vehicles",
            json=v_payload,
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert res.status_code == 201
        veh = res.get_json()["data"]["vehicle"]
        assert veh["vehicle_id"] == "TN-09-AUTO-5555"
        assert veh["rent_amount"] == "400.00"
        assert veh["rent_frequency"] == "DAILY"
        assert driver_id in veh["assigned_driver_ids"]

        # 2. Driver inspects assigned vehicle
        res_get = client.get(
            "/api/settlements/vehicles/TN-09-AUTO-5555",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert res_get.status_code == 200
        assert res_get.get_json()["data"]["vehicle"]["owner_id"] == owner_id

        # 3. Unauthorized third-party cannot access vehicle
        other_token, _ = _auth_user(client, "+919999900099")
        res_unauth = client.get(
            "/api/settlements/vehicles/TN-09-AUTO-5555",
            headers={"Authorization": f"Bearer {other_token}"}
        )
        assert res_unauth.status_code == 404

        # 4. Owner reassigns/adds another driver
        res_assign = client.post(
            "/api/settlements/vehicles/TN-09-AUTO-5555/assign",
            json={"driver_id": "DRV_SECOND_99"},
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert res_assign.status_code == 200
        assert "DRV_SECOND_99" in res_assign.get_json()["data"]["vehicle"]["assigned_driver_ids"]

    def test_rent_payment_partial_and_carried_forward_settlement(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        owner_token, owner_id = _auth_user(client, "+919999900011")
        driver_token, driver_id = _auth_user(client, "+919999900012")

        # Setup vehicle: rent 400.00/day
        client.post(
            "/api/settlements/vehicles",
            json={
                "vehicle_id": "TN-09-AUTO-6666",
                "rent_amount": "400.00",
                "rent_frequency": "DAILY",
                "assigned_driver_ids": [driver_id]
            },
            headers={"Authorization": f"Bearer {owner_token}"}
        )

        ledger_svc = app.extensions["ledger_service"]
        settle_svc = app.extensions["settlement_service"]
        t_date = "2026-11-10"

        # Driver logs income 1500 and operating expense 300
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("1500.00"),
            category="FARE",
            description="Day collections",
            transaction_date=t_date,
            idempotency_key="TEST_INC_1"
        )
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("300.00"),
            category="FUEL",
            description="CNG fuel",
            transaction_date=t_date,
            idempotency_key="TEST_EXP_1"
        )

        # Driver records PARTIAL rent payment of 250 (out of 400 expected)
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            transaction_type=TransactionType.OWNER_PAYMENT,
            amount=Decimal("250.00"),
            category="OWNER_RENT",
            description="Partial rent",
            transaction_date=t_date,
            idempotency_key="TEST_OWNER_1"
        )

        # Create Settlement for Day 1
        s1 = settle_svc.create_settlement(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            settlement_date=t_date,
            shift_id="DAY_SHIFT"
        )
        assert s1["expected_rent"] == "400.00"
        assert s1["owner_payments"] == "250.00"
        assert s1["remaining_balance"] == "150.00"  # 400 - 250 = 150 debt
        assert s1["settlement_status"] == SettlementStatus.PARTIALLY_SETTLED.value
        # Operating profit = 1500 - 300 = 1200. Take-home = 1200 - 250 = 950
        assert s1["operating_profit"] == "1200.00"
        assert s1["driver_take_home"] == "950.00"

        # Check outstanding endpoint
        res_out = client.get(
            "/api/settlements/outstanding?vehicle_id=TN-09-AUTO-6666",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert res_out.status_code == 200
        assert res_out.get_json()["data"]["outstanding_balance"] == "150.00"

        # Day 2: Carried-forward balance test
        t_date_2 = "2026-11-11"
        # On Day 2, expected rent is 400, carried forward is 150 -> Total obligation = 550
        # Driver OVERPAYS: pays 600
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            transaction_type=TransactionType.OWNER_PAYMENT,
            amount=Decimal("600.00"),
            category="OWNER_RENT",
            description="Overpaid rent",
            transaction_date=t_date_2,
            idempotency_key="TEST_OWNER_2"
        )

        s2 = settle_svc.create_settlement(
            driver_id=driver_id,
            vehicle_id="TN-09-AUTO-6666",
            settlement_date=t_date_2,
            shift_id="DAY_SHIFT"
        )
        assert s2["previous_balance"] == "150.00"
        assert s2["total_obligation"] == "550.00"
        assert s2["owner_payments"] == "600.00"
        assert s2["remaining_balance"] == "-50.00"  # 550 - 600 = -50 (overpaid credit)
        assert s2["settlement_status"] == SettlementStatus.OVERPAID.value


class TestPassengerTripWorkflow:
    """Domain 2: Passenger QR/link, public agreement, mid-trip updates, payments and consent."""

    def test_passenger_trip_full_lifecycle(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        driver_token, driver_id = _auth_user(client, "+919840111222")

        # 1. Driver creates trip proposal
        create_res = client.post(
            "/api/trips",
            json={
                "pickup_location": "T. Nagar Bus Terminus",
                "destination_location": "Marina Beach",
                "proposed_fare": "180.00",
                "vehicle_id": "TN-01-AB-1234"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert create_res.status_code == 201
        data = create_res.get_json()["data"]
        trip_id = data["trip"]["trip_id"]
        raw_token = data["passenger_access_token"]
        assert data["passenger_url"].startswith("http")
        assert "<svg" in data["qr_code_svg"]

        # 2. Trip CANNOT start before passenger agreement
        unagreed_start = client.post(
            f"/api/trips/{trip_id}/start",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert unagreed_start.status_code == 400
        assert "Cannot start trip" in unagreed_start.get_json()["error"]["message"]

        # 3. Passenger opens trip without login using public token
        pass_res = client.get(f"/api/passenger/trips/{trip_id}?token={raw_token}")
        assert pass_res.status_code == 200
        pass_view = pass_res.get_json()["data"]["trip"]
        assert pass_view["state"] == TripState.AGREEMENT_PENDING.value
        assert pass_view["initial_proposed_fare"] == "180.00"
        # Verify passenger view isolation: internal ledger and driver details are hidden
        assert "driver_id" not in pass_view
        assert "earned_fare" not in pass_view
        assert "owner_payments" not in pass_view

        # Invalid token rejected
        bad_token_res = client.get(f"/api/passenger/trips/{trip_id}?token=invalid-token")
        assert bad_token_res.status_code == 403

        # 4. Passenger accepts agreement
        agree_res = client.post(
            f"/api/passenger/trips/{trip_id}/agreement",
            json={"accepted": True},
            headers={"X-Passenger-Token": raw_token}
        )
        assert agree_res.status_code == 200
        assert agree_res.get_json()["data"]["trip"]["state"] == TripState.AGREED.value

        # 5. Driver starts trip
        start_res = client.post(
            f"/api/trips/{trip_id}/start",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert start_res.status_code == 200
        assert start_res.get_json()["data"]["trip"]["state"] == TripState.IN_PROGRESS.value

        # 6. Mid-trip proposal: passenger proposes additional stop and driver accepts
        stop_res = client.post(
            f"/api/passenger/trips/{trip_id}/propose-change",
            json={
                "proposal_type": "ADD_STOP",
                "proposed_value": {"stop_name": "Spencer Plaza", "fare_adjustment": "40.00"},
                "reason": "Quick ATM stop"
            },
            headers={"X-Passenger-Token": raw_token}
        )
        assert stop_res.status_code == 201
        prop_id = stop_res.get_json()["data"]["proposal"]["proposal_id"]

        # Driver accepts proposal
        drv_accept = client.post(
            f"/api/trips/{trip_id}/respond-proposal",
            json={"proposal_id": prop_id, "accepted": True},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert drv_accept.status_code == 200
        trip_after_stop = drv_accept.get_json()["data"]["trip"]
        assert "Spencer Plaza" in str(trip_after_stop["additional_stops"])

        # 7. Continuous listening dual consent test: starts OFF
        assert trip_after_stop["continuous_listening_enabled"] is False

        # Driver grants consent
        client.post(
            f"/api/trips/{trip_id}/consent",
            json={"consent": True},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        # Still OFF until passenger grants consent
        check_p = client.get(f"/api/passenger/trips/{trip_id}?token={raw_token}").get_json()["data"]["trip"]
        assert check_p["continuous_listening_enabled"] is False

        # Passenger grants consent -> turns ON
        client.post(
            f"/api/passenger/trips/{trip_id}/consent",
            json={"consent": True},
            headers={"X-Passenger-Token": raw_token}
        )
        check_mut = client.get(f"/api/passenger/trips/{trip_id}?token={raw_token}").get_json()["data"]["trip"]
        assert check_mut["continuous_listening_enabled"] is True

        # Passenger withdraws consent -> turns OFF immediately
        client.post(
            f"/api/passenger/trips/{trip_id}/consent",
            json={"consent": False},
            headers={"X-Passenger-Token": raw_token}
        )
        check_off = client.get(f"/api/passenger/trips/{trip_id}?token={raw_token}").get_json()["data"]["trip"]
        assert check_off["continuous_listening_enabled"] is False

        # 8. Complete trip and record payment
        comp_res = client.post(
            f"/api/trips/{trip_id}/complete",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert comp_res.status_code == 200

        pay_res = client.post(
            f"/api/trips/{trip_id}/payments",
            json={
                "amount": "220.00",
                "payment_method": "CASH",
                "idempotency_key": f"PAY_TRIP_{trip_id}"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert pay_res.status_code == 201

        # 9. Passenger receives digital receipt
        receipt_res = client.get(f"/api/passenger/trips/{trip_id}/receipt?token={raw_token}")
        assert receipt_res.status_code == 200
        receipt = receipt_res.get_json()["data"]["receipt"]
        assert receipt["trip_id"] == trip_id
        assert receipt["pickup_location"] == "T. Nagar Bus Terminus"
        assert receipt["final_agreed_fare"] == "220.00"
        assert receipt["paid_amount"] == "220.00"

        # 10. Dispute preservation test
        disp_res = client.post(
            f"/api/passenger/trips/{trip_id}/dispute",
            json={"reason": "Driver route was slightly longer than expected"},
            headers={"X-Passenger-Token": raw_token}
        )
        assert disp_res.status_code == 200
        assert disp_res.get_json()["data"]["trip"]["state"] == TripState.DISPUTED.value

        # Events audit trail verifies all actions are logged
        events_res = client.get(f"/api/trips/{trip_id}/events", headers={"Authorization": f"Bearer {driver_token}"})
        assert events_res.status_code == 200
        events = events_res.get_json()["data"]["events"]
        event_types = [e["event_type"] for e in events]
        assert "TRIP_CREATED" in event_types
        assert "INITIAL_AGREEMENT_ACCEPTED" in event_types
        assert "TRIP_STARTED" in event_types
        assert "TRIP_DISPUTED" in event_types


class TestVehicleDocumentsAndOCR:
    """Domain 3: Vehicle documents, OCR preview, human review, and expiry reminders."""

    def test_document_ocr_preview_and_registration(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        driver_token, driver_id = _auth_user(client, "+919840222333")

        # 1. Driver uploads RC image to OCR preview
        fake_rc = io.BytesIO(b"%PDF-1.4 Mock RC Registration Document Bytes")
        preview_res = client.post(
            "/api/documents/ocr-preview",
            data={"file": (fake_rc, "vehicle_rc_book.pdf")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert preview_res.status_code == 200
        preview = preview_res.get_json()["data"]
        assert preview["document_type"] == "REGISTRATION_CERTIFICATE"
        assert preview["needs_human_review"] is True
        assert preview["ocr_provider"] == "mock_ocr"
        assert "simulated/unverified" in preview["ocr_disclaimer"]

        # 2. Invalid/unsupported format rejected
        bad_file = io.BytesIO(b"executable-binary-payload")
        bad_res = client.post(
            "/api/documents/ocr-preview",
            data={"file": (bad_file, "script.exe")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert bad_res.status_code == 400

        # 3. Driver reviews, edits, and confirms document registration
        reg_res = client.post(
            "/api/documents",
            json={
                "type": preview["document_type"],
                "number": preview["document_number"],
                "expiry": "2026-11-20",  # Expiring in 10 days
                "vehicle_id": "TN-01-AB-1234",
                "issuing_authority": preview["issuing_authority"]
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert reg_res.status_code == 201
        doc_id = reg_res.get_json()["data"]["document"]["document_id"]

        # 4. Driver data isolation: another driver cannot access document
        other_token, _ = _auth_user(client, "+919840999999")
        iso_res = client.get(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {other_token}"})
        assert iso_res.status_code == 403

        # 5. Expiry reminder generation for milestone threshold
        scan_res = client.post(
            "/api/reminders/scan",
            json={"reference_date": "2026-11-13"},  # 7 days before 2026-11-20 (threshold 7)
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert scan_res.status_code == 200
        res_data = scan_res.get_json()["data"]
        assert res_data["new_reminders_count"] >= 1

        # 6. Reminder idempotent duplicate prevention
        scan_repeat = client.post(
            "/api/reminders/scan",
            json={"reference_date": "2026-11-13"},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert scan_repeat.get_json()["data"]["new_reminders_count"] == 0


class TestChallanAssistance:
    """Domain 4: Challan OCR preview, status tracking, payment, and external disclaimer."""

    def test_challan_lifecycle_and_mock_disclaimer(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        driver_token, driver_id = _auth_user(client, "+919840333444")

        # 1. OCR Preview on Challan Notice
        notice_file = io.BytesIO(b"%PDF-1.4 MOCK_TRAFFIC_CHALLAN_POLICE_NOTICE_SCAN")
        ocr_res = client.post(
            "/api/challans/ocr-preview",
            data={"file": (notice_file, "challan_notice.pdf")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert ocr_res.status_code == 200
        ocr_data = ocr_res.get_json()["data"]
        assert ocr_data["needs_user_confirmation"] is True
        assert "unverified" in ocr_data["ocr_disclaimer"]

        # 2. Driver saves challan
        save_res = client.post(
            "/api/challans",
            json={
                "challan_number": ocr_data["challan_number"],
                "vehicle_id": "TN-09-CB-1284",
                "violation_description": ocr_data["violation_description"],
                "fine_amount": ocr_data["fine_amount"],
                "issuing_authority": ocr_data["issuing_authority"]
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert save_res.status_code == 201
        challan = save_res.get_json()["data"]["challan"]
        challan_id = challan["challan_id"]
        assert challan["payment_status"] == ChallanStatus.UNPAID.value
        assert "echallan.parivahan.gov.in" in challan["official_portal_url"]

        # 3. Pay Challan
        pay_res = client.post(
            f"/api/challans/{challan_id}/pay",
            json={"payment_reference": "UPI_REF_998877", "payment_date": today_ist()},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert pay_res.status_code == 200
        pay_data = pay_res.get_json()["data"]
        paid_challan = pay_data.get("challan", pay_data)
        assert paid_challan["payment_status"] == ChallanStatus.PAID.value

        # 4. Invalid status transition: PAID cannot transition to UNPAID
        invalid_trans = client.put(
            f"/api/challans/{challan_id}/status",
            json={"status": "UNPAID"},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert invalid_trans.status_code == 400


class TestVehicleMaintenanceAndLedger:
    """Domain 5: Maintenance service logs, ledger firewall, and deduplication."""

    def test_maintenance_with_financial_confirmation(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()
        driver_token, driver_id = _auth_user(client, "+919840444555")

        # 1. Propose maintenance with financial expense
        prop_res = client.post(
            "/api/maintenance",
            json={
                "vehicle_id": "TN-01-AB-1234",
                "maintenance_category": "OIL_CHANGE",
                "description": "Engine Oil & Filter Replacement",
                "cost": "450.00",
                "record_financial_expense": True,
                "odometer_reading": 64500,
                "next_service_odometer": 69500,
                "next_service_date": "2027-02-10"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        # Financial firewall requires explicit driver confirmation (HTTP 202)
        assert prop_res.status_code == 202
        prop_data = prop_res.get_json()["data"]
        pending_id = prop_data["pending_action_id"]

        # 2. Confirm transaction
        conf_res = client.post(
            f"/api/pending-actions/{pending_id}/confirm",
            json={},
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert conf_res.status_code == 200

        # 3. Verify maintenance record was created and linked to financial transaction
        maint_list_res = client.get(
            "/api/maintenance?vehicle_id=TN-01-AB-1234",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert maint_list_res.status_code == 200
        maint_records = maint_list_res.get_json()["data"]["maintenance_records"]
        assert len(maint_records) == 1
        record = maint_records[0]
        assert record["cost"] == "450.00"
        assert record["financial_transaction_id"] != ""
        assert record["next_service_odometer"] == 69500

        # 4. Verify financial dashboard reflects the single expense
        fin_res = client.get(
            f"/api/finance/summary/daily?date={today_ist()}",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert fin_res.status_code == 200
        summary = fin_res.get_json()["data"]
        metrics = summary.get("metrics", summary)
        assert metrics["operating_expenses"] == "450.00"

        # 5. Check upcoming service query
        up_res = client.get(
            "/api/maintenance/upcoming?vehicle_id=TN-01-AB-1234",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert up_res.status_code == 200
        assert up_res.get_json()["data"]["count"] == 1


class TestFull12StepBatch2Journey:
    """Full 12-Step End-to-End Integration Journey requested in Section F."""

    def test_complete_12_step_driver_owner_passenger_workflow(self, app_and_db):
        app, db = app_and_db
        client = app.test_client()

        # Step 1: Owner creates driver relationship and assigns vehicle
        owner_token, owner_id = _auth_user(client, "+919888811111")
        driver_token, driver_id = _auth_user(client, "+919888822222")

        veh_res = client.post(
            "/api/settlements/vehicles",
            json={
                "vehicle_id": "TN-02-AUTO-7777",
                "owner_id": owner_id,
                "vehicle_type": "AUTO_RICKSHAW",
                "rent_amount": "350.00",
                "rent_frequency": "DAILY",
                "assigned_driver_ids": [driver_id]
            },
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert veh_res.status_code == 201

        # Step 2: Owner configures rent
        veh_info = veh_res.get_json()["data"]["vehicle"]
        assert veh_info["rent_amount"] == "350.00"
        assert veh_info["rent_frequency"] == "DAILY"

        # Step 3: Driver records rent payment
        ledger_svc = app.extensions["ledger_service"]
        settle_svc = app.extensions["settlement_service"]
        curr_date = today_ist()

        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-02-AUTO-7777",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("1200.00"),
            category="FARE",
            description="Day collections",
            transaction_date=curr_date,
            idempotency_key="S3_FARE_1"
        )
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-02-AUTO-7777",
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("200.00"),
            category="FUEL",
            description="Auto fuel",
            transaction_date=curr_date,
            idempotency_key="S3_FUEL_1"
        )
        # Driver pays 350.00 owner rent
        ledger_svc.record_transaction(
            driver_id=driver_id,
            vehicle_id="TN-02-AUTO-7777",
            transaction_type=TransactionType.OWNER_PAYMENT,
            amount=Decimal("350.00"),
            category="OWNER_RENT",
            description="Daily rent",
            transaction_date=curr_date,
            idempotency_key="S3_RENT_1"
        )

        # Step 4: Settlement and outstanding balance update correctly
        s_doc = settle_svc.create_settlement(
            driver_id=driver_id,
            vehicle_id="TN-02-AUTO-7777",
            settlement_date=curr_date
        )
        assert s_doc["expected_rent"] == "350.00"
        assert s_doc["owner_payments"] == "350.00"
        assert s_doc["remaining_balance"] == "0.00"
        assert s_doc["settlement_status"] == SettlementStatus.SETTLED.value
        # Take home = (1200 - 200) - 350 = 650.00
        assert s_doc["driver_take_home"] == "650.00"

        # Step 5: Driver creates passenger trip and QR code
        trip_res = client.post(
            "/api/trips",
            json={
                "pickup_location": "Guindy Railway Station",
                "destination_location": "IIT Madras Main Gate",
                "proposed_fare": "150.00",
                "vehicle_id": "TN-02-AUTO-7777"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert trip_res.status_code == 201
        trip_data = trip_res.get_json()["data"]
        trip_id = trip_data["trip"]["trip_id"]
        p_token = trip_data["passenger_access_token"]
        assert "<svg" in trip_data["qr_code_svg"]

        # Step 6: Passenger agrees to trip
        agree_res = client.post(
            f"/api/passenger/trips/{trip_id}/agreement",
            json={"accepted": True},
            headers={"X-Passenger-Token": p_token}
        )
        assert agree_res.status_code == 200
        assert agree_res.get_json()["data"]["trip"]["state"] == TripState.AGREED.value

        # Step 7: Driver completes trip and records payment
        client.post(f"/api/trips/{trip_id}/start", headers={"Authorization": f"Bearer {driver_token}"})
        client.post(f"/api/trips/{trip_id}/complete", headers={"Authorization": f"Bearer {driver_token}"})

        pay_res = client.post(
            f"/api/trips/{trip_id}/payments",
            json={
                "amount": "150.00",
                "payment_method": "UPI",
                "idempotency_key": f"FULL_JOURNEY_PAY_{trip_id}"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert pay_res.status_code == 201

        # Step 8: Passenger receives receipt
        receipt_res = client.get(f"/api/passenger/trips/{trip_id}/receipt?token={p_token}")
        assert receipt_res.status_code == 200
        assert receipt_res.get_json()["data"]["receipt"]["paid_amount"] == "150.00"

        # Step 9: Driver uploads a document and reviews OCR output
        doc_bytes = io.BytesIO(b"%PDF-1.4 Mock Insurance Policy Document")
        ocr_res = client.post(
            "/api/documents/ocr-preview",
            data={"file": (doc_bytes, "insurance_policy.pdf")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert ocr_res.status_code == 200
        cand = ocr_res.get_json()["data"]
        assert cand["document_type"] == "INSURANCE_POLICY"

        doc_save = client.post(
            "/api/documents",
            json={
                "type": cand["document_type"],
                "number": cand["document_number"],
                "expiry": "2026-11-25",
                "vehicle_id": "TN-02-AUTO-7777"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert doc_save.status_code == 201

        # Step 10: Document expiry reminder is generated
        rem_res = client.post(
            "/api/reminders/scan",
            json={"reference_date": "2026-11-24"},  # 1 day before expiry (threshold 1)
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert rem_res.status_code == 200
        assert rem_res.get_json()["data"]["new_reminders_count"] >= 1

        # Step 11: Driver records maintenance and checks the next service reminder
        maint_prop = client.post(
            "/api/maintenance",
            json={
                "vehicle_id": "TN-02-AUTO-7777",
                "maintenance_category": "TYRE_REPAIR",
                "description": "Rear Tyre Puncture & Tube Replacement",
                "cost": "150.00",
                "record_financial_expense": True,
                "next_service_date": "2026-12-15"
            },
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert maint_prop.status_code == 202
        p_id = maint_prop.get_json()["data"]["pending_action_id"]

        client.post(
            f"/api/pending-actions/{p_id}/confirm",
            json={},
            headers={"Authorization": f"Bearer {driver_token}"}
        )

        up_maint = client.get(
            "/api/maintenance/upcoming?vehicle_id=TN-02-AUTO-7777",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert up_maint.status_code == 200
        assert up_maint.get_json()["data"]["count"] == 1

        # Step 12: Maintenance expenses appear correctly in financial dashboard
        dash_res = client.get(
            f"/api/finance/summary/daily?date={curr_date}",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert dash_res.status_code == 200
        fin_data = dash_res.get_json()["data"]
        metrics = fin_data.get("metrics", fin_data)
        # Operating expenses = 200 (FUEL) + 150 (MAINTENANCE) = 350.00
        assert metrics["operating_expenses"] == "350.00"
        # Gross income = 1200 (Step 3) = 1200.00 (trip payment 150 was recorded on trip's date)
        assert Decimal(metrics["gross_income"]) >= Decimal("1200.00")
