"""
API Integration Tests for Vehicle Maintenance Management.
Tests endpoints under /api/maintenance: standalone logging, financial ledger
proposal & confirmation workflow, upcoming schedules, and spending summary.
"""

import json
import pytest
from decimal import Decimal


def get_driver_token(client, phone="9876543701"):
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_maintenance_unauthenticated_access_rejected(client):
    res = client.get("/api/maintenance")
    assert res.status_code == 401


def test_standalone_maintenance_creation(client):
    token, driver_id = get_driver_token(client, "9876543702")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    res = client.post(
        "/api/maintenance",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "TN-09-CB-1284",
            "maintenance_category": "ENGINE_OIL",
            "description": "Castrol 20W40 oil change",
            "cost": "450.00",
            "service_provider": "Shanmugam Garage",
            "odometer_reading": 64280,
            "next_service_date": "2026-12-20",
            "next_service_odometer": 69280,
            "record_financial_expense": False
        })
    )
    assert res.status_code == 201
    maint_data = res.get_json()["data"]["maintenance"]
    assert maint_data["maintenance_id"].startswith("MNT_")
    assert maint_data["cost"] == "450.00"
    assert maint_data["category_label"] == "Engine Oil & Oil Filter Change"


def test_maintenance_financial_proposal_and_confirmation(client):
    token, driver_id = get_driver_token(client, "9876543703")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Propose maintenance with financial expense
    prop_res = client.post(
        "/api/maintenance",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "TN-09-CB-1284",
            "maintenance_category": "BRAKE_SERVICING",
            "description": "Brake drum overhaul",
            "cost": "380.00",
            "service_provider": "City Auto Care",
            "record_financial_expense": True
        })
    )
    # Returns 202 Accepted with pending action
    assert prop_res.status_code == 202
    prop_data = prop_res.get_json()["data"]
    pending_id = prop_data["pending_action_id"]
    assert pending_id.startswith("PEND_")

    # 2. Confirm pending action via /api/pending-actions/<id>/confirm
    confirm_res = client.post(
        f"/api/pending-actions/{pending_id}/confirm",
        headers=headers,
        data=json.dumps({"idempotency_key": f"CONFIRM_API_{pending_id}"})
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.get_json()["data"]
    assert confirm_data["status"] == "COMPLETED"
    txn_id = confirm_data["transaction_id"]

    # 3. Verify maintenance record exists and links to txn_id
    list_res = client.get("/api/maintenance", headers=headers)
    assert list_res.status_code == 200
    records = list_res.get_json()["data"]["maintenance_records"]
    matched = [r for r in records if r.get("financial_transaction_id") == txn_id]
    assert len(matched) == 1
    assert matched[0]["cost"] == "380.00"


def test_upcoming_and_spending_summary_endpoints(client):
    token, _ = get_driver_token(client, "9876543704")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Add record with future next_service_date
    client.post(
        "/api/maintenance",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "TN-09-CB-1284",
            "maintenance_category": "TYRE_REPLACEMENT",
            "description": "Front tyre replaced",
            "cost": "1250.00",
            "next_service_date": "2026-12-31"
        })
    )

    # Check upcoming
    up_res = client.get("/api/maintenance/upcoming", headers=headers)
    assert up_res.status_code == 200
    upcoming = up_res.get_json()["data"]["upcoming_services"]
    assert len(upcoming) >= 1

    # Check summary
    summ_res = client.get("/api/maintenance/summary?start_date=2026-01-01&end_date=2026-12-31", headers=headers)
    assert summ_res.status_code == 200
    summ = summ_res.get_json()["data"]
    assert Decimal(summ["total_spending"]) >= Decimal("1250.00")
