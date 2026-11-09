"""
API Integration tests for T2T DRIVE Passenger Extension:
Driver Trips API and Lightweight Passenger Public Access API.
"""

import json
import pytest
from decimal import Decimal


def get_driver_auth(client, phone="9876543401"):
    """Helper to authenticate a driver and retrieve JWT bearer token."""
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return {
        "Authorization": f"Bearer {data['token']}",
        "Content-Type": "application/json"
    }, data["driver"]["driver_id"]


def test_complete_trip_lifecycle_api(client):
    headers1, driver_id1 = get_driver_auth(client, "9876543402")

    # 1. Driver creates trip
    create_res = client.post(
        "/api/trips",
        headers=headers1,
        data=json.dumps({
            "pickup_location": "Salem New Bus Stand",
            "destination_location": "Salem Railway Junction",
            "proposed_fare": 180.00,
            "vehicle_id": "TN-27-AA-9999"
        })
    )
    assert create_res.status_code == 201
    res_data = create_res.get_json()["data"]
    trip_id = res_data["trip"]["trip_id"]
    passenger_token = res_data["passenger_access_token"]
    assert res_data["trip"]["state"] == "AGREEMENT_PENDING"
    assert "<svg" in res_data["qr_code_svg"]

    # 2. Driver retrieves active trip
    active_res = client.get("/api/trips/active", headers=headers1)
    assert active_res.status_code == 200
    assert active_res.get_json()["data"]["trip"]["trip_id"] == trip_id

    # 3. Passenger views trip (public access via query param token)
    pass_view_res = client.get(f"/api/passenger/trips/{trip_id}?token={passenger_token}")
    assert pass_view_res.status_code == 200
    pass_view = pass_view_res.get_json()["data"]["trip"]
    assert pass_view["trip_id"] == trip_id
    assert pass_view["destination_location"] == "Salem Railway Junction"
    assert "driver_id" not in pass_view  # Privacy preserved!

    # 4. Passenger agrees to initial fare
    agree_res = client.post(
        f"/api/passenger/trips/{trip_id}/agreement",
        headers={"X-Passenger-Token": passenger_token, "Content-Type": "application/json"},
        data=json.dumps({"accepted": True})
    )
    assert agree_res.status_code == 200
    assert agree_res.get_json()["data"]["trip"]["state"] == "AGREED"

    # 5. Driver starts trip
    start_res = client.post(f"/api/trips/{trip_id}/start", headers=headers1)
    assert start_res.status_code == 200
    assert start_res.get_json()["data"]["trip"]["state"] == "IN_PROGRESS"

    # 6. Driver proposes destination change
    prop_res = client.post(
        f"/api/trips/{trip_id}/propose-change",
        headers=headers1,
        data=json.dumps({
            "proposal_type": "DESTINATION_CHANGE",
            "proposed_value": {"destination_location": "Steel Plant Main Gate"},
            "reason": "Passenger requested drop extension"
        })
    )
    assert prop_res.status_code == 201
    prop_data = prop_res.get_json()["data"]["proposal"]
    prop_id = prop_data["proposal_id"]

    # 7. Passenger accepts destination change
    pass_resp_res = client.post(
        f"/api/passenger/trips/{trip_id}/respond-proposal",
        headers={"X-Passenger-Token": passenger_token, "Content-Type": "application/json"},
        data=json.dumps({"proposal_id": prop_id, "accepted": True})
    )
    assert pass_resp_res.status_code == 200
    assert pass_resp_res.get_json()["data"]["trip"]["destination_location"] == "Steel Plant Main Gate"

    # 8. Mutual consent for continuous listening
    d_consent_res = client.post(
        f"/api/trips/{trip_id}/consent",
        headers=headers1,
        data=json.dumps({"consented": True})
    )
    assert d_consent_res.status_code == 200

    p_consent_res = client.post(
        f"/api/passenger/trips/{trip_id}/consent",
        headers={"X-Passenger-Token": passenger_token, "Content-Type": "application/json"},
        data=json.dumps({"consented": True})
    )
    assert p_consent_res.status_code == 200

    # 9. Start continuous listening
    listen_start_res = client.post(f"/api/trips/{trip_id}/listening/start", headers=headers1)
    assert listen_start_res.status_code == 200
    assert listen_start_res.get_json()["data"]["is_active"] is True

    # 10. Record payment: ₹180 full fare
    pay_res = client.post(
        f"/api/trips/{trip_id}/payments",
        headers=headers1,
        data=json.dumps({
            "amount": 180.00,
            "payment_method": "UPI",
            "idempotency_key": f"API_PAY_{trip_id}_01"
        })
    )
    assert pay_res.status_code in (200, 201)
    pay_data = pay_res.get_json()["data"]
    assert pay_data["payment_status"] == "PAID"
    assert pay_data["outstanding_amount"] == "0.00"

    # 11. Complete trip
    comp_res = client.post(f"/api/trips/{trip_id}/complete", headers=headers1)
    assert comp_res.status_code == 200
    assert comp_res.get_json()["data"]["trip"]["state"] == "COMPLETED"

    # 12. Passenger generates digital receipt
    receipt_res = client.get(
        f"/api/passenger/trips/{trip_id}/receipt?token={passenger_token}"
    )
    assert receipt_res.status_code == 200
    receipt = receipt_res.get_json()["data"]["receipt"]
    assert receipt["trip_id"] == trip_id
    assert receipt["payment_status"] == "PAID"
    assert receipt["total_paid"] == "180.00"
    assert receipt["vehicle_id"] == "TN-27-AA-9999"


def test_cross_driver_and_passenger_security(client):
    headers1, driver_id1 = get_driver_auth(client, "9876543403")
    headers2, driver_id2 = get_driver_auth(client, "9876543404")

    # Driver 1 creates trip
    create_res = client.post(
        "/api/trips",
        headers=headers1,
        data=json.dumps({
            "pickup_location": "Airport",
            "destination_location": "Guindy",
            "proposed_fare": 200.00
        })
    )
    trip_id = create_res.get_json()["data"]["trip"]["trip_id"]
    token1 = create_res.get_json()["data"]["passenger_access_token"]

    # Security A: Driver 2 cannot start or access Driver 1's trip
    d2_res = client.post(f"/api/trips/{trip_id}/start", headers=headers2)
    assert d2_res.status_code == 400 or d2_res.status_code == 403

    # Security B: Passenger without token cannot view trip
    unauth_pass_res = client.get(f"/api/passenger/trips/{trip_id}")
    assert unauth_pass_res.status_code == 401

    # Security C: Passenger with invalid token cannot view trip
    bad_token_res = client.get(f"/api/passenger/trips/{trip_id}?token=invalid-fake-token")
    assert bad_token_res.status_code == 403

    # Security D: Driver 2 creates a separate trip
    create_res2 = client.post(
        "/api/trips",
        headers=headers2,
        data=json.dumps({
            "pickup_location": "Central",
            "destination_location": "Egmore",
            "proposed_fare": 100.00
        })
    )
    trip_id2 = create_res2.get_json()["data"]["trip"]["trip_id"]

    # Security E: Passenger Token from Trip 1 CANNOT access Trip 2
    cross_res = client.get(f"/api/passenger/trips/{trip_id2}?token={token1}")
    assert cross_res.status_code == 403
