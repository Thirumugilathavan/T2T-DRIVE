"""
API Integration Tests for Vehicle Reminders.
Tests endpoints under /api/reminders: scan trigger, list, and acknowledge.
"""

import json
import pytest


def get_driver_token(client, phone="9876543801"):
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_reminders_unauthenticated_access_rejected(client):
    res = client.get("/api/reminders")
    assert res.status_code == 401


def test_reminder_scan_and_acknowledge_api(client):
    token, driver_id = get_driver_token(client, "9876543802")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Register a document expiring in exactly 7 days
    client.post(
        "/api/documents",
        headers=headers,
        data=json.dumps({
            "type": "PUC",
            "number": "PUC-REM-7D",
            "expiry": "2026-11-15",
            "vehicle_id": "TN-09-CB-1284"
        })
    )

    # 2. Trigger scan with reference_date="2026-11-08" (7 days before)
    scan_res = client.post(
        "/api/reminders/scan",
        headers=headers,
        data=json.dumps({"reference_date": "2026-11-08"})
    )
    assert scan_res.status_code == 200
    scan_data = scan_res.get_json()["data"]
    assert scan_data["new_reminders_count"] >= 1

    # 3. List reminders
    list_res = client.get("/api/reminders", headers=headers)
    assert list_res.status_code == 200
    reminders = list_res.get_json()["data"]["reminders"]
    assert len(reminders) >= 1
    rem_id = reminders[0]["reminder_id"]

    # 4. Acknowledge reminder
    ack_res = client.post(f"/api/reminders/{rem_id}/acknowledge", headers=headers)
    assert ack_res.status_code == 200
