"""
API Integration Tests for Traffic Challans.
Tests endpoints under /api/challans: manual creation, OCR preview,
payment recording, status transitions, and cross-driver isolation.
"""

import io
import json
import pytest


def get_driver_token(client, phone="9876543601"):
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_challans_unauthenticated_access_rejected(client):
    res = client.get("/api/challans")
    assert res.status_code == 401


def test_add_and_list_challans(client):
    token, driver_id = get_driver_token(client, "9876543602")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Add challan
    add_res = client.post(
        "/api/challans",
        headers=headers,
        data=json.dumps({
            "challan_number": "TN0920261199",
            "vehicle_id": "TN-09-CB-1284",
            "violation_description": "Signal jump at Anna Salai junction",
            "fine_amount": "500.00"
        })
    )
    assert add_res.status_code == 201
    chln_data = add_res.get_json()["data"]["challan"]
    chln_id = chln_data["challan_id"]
    assert chln_data["payment_status"] == "UNPAID"

    # 2. List unpaid challans
    unpaid_res = client.get("/api/challans/unpaid", headers={"Authorization": f"Bearer {token}"})
    assert unpaid_res.status_code == 200
    unpaid_data = unpaid_res.get_json()["data"]
    assert unpaid_data["count"] >= 1
    assert any(c["challan_id"] == chln_id for c in unpaid_data["unpaid_challans"])


def test_challan_payment_flow(client):
    token, _ = get_driver_token(client, "9876543603")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Add challan
    add_res = client.post(
        "/api/challans",
        headers=headers,
        data=json.dumps({
            "challan_number": "TN09PAY8877",
            "vehicle_id": "TN-09-CB-1284",
            "violation_description": "No parking on high road",
            "fine_amount": "200.00"
        })
    )
    chln_id = add_res.get_json()["data"]["challan"]["challan_id"]

    # Record payment
    pay_res = client.post(
        f"/api/challans/{chln_id}/payment",
        headers=headers,
        data=json.dumps({
            "payment_date": "2026-11-08",
            "payment_reference": "UPI/2026/8827162"
        })
    )
    assert pay_res.status_code == 200
    paid_data = pay_res.get_json()["data"]
    assert paid_data["payment_status"] == "PAID"
    assert paid_data["payment_reference"] == "UPI/2026/8827162"


def test_ocr_preview_endpoint(client):
    token, _ = get_driver_token(client, "9876543604")
    auth_headers = {"Authorization": f"Bearer {token}"}

    fake_pdf = b"%PDF-1.4\nSimulated Traffic Challan notice\n%%EOF"
    res = client.post(
        "/api/challans/ocr-preview",
        headers=auth_headers,
        data={"file": (io.BytesIO(fake_pdf), "challan_notice.pdf")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["needs_user_confirmation"] is True
    assert "ocr_disclaimer" in data
    assert "fine_amount" in data


def test_cross_driver_challan_access_rejected(client):
    token_alice, _ = get_driver_token(client, "9876543605")
    token_bob, _ = get_driver_token(client, "9876543606")

    # Alice creates challan
    add_res = client.post(
        "/api/challans",
        headers={"Authorization": f"Bearer {token_alice}", "Content-Type": "application/json"},
        data=json.dumps({
            "challan_number": "ALICE_CHLN_9",
            "vehicle_id": "TN-09-CB-1284",
            "violation_description": "Speeding",
            "fine_amount": "1000.00"
        })
    )
    chln_id = add_res.get_json()["data"]["challan"]["challan_id"]

    # Bob attempts to view
    bob_res = client.get(f"/api/challans/{chln_id}", headers={"Authorization": f"Bearer {token_bob}"})
    assert bob_res.status_code == 403
