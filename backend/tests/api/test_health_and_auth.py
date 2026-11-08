import json

def test_health_check_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["status"] == "UP"
    assert "version" in data["data"]


def test_db_health_endpoint(client):
    res = client.get("/api/health/db")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["database_connected"] is True


def test_db_health_endpoint_failure(client, monkeypatch):
    from app.database.connection import db_manager
    monkeypatch.setattr(db_manager, "is_connected", lambda: False)
    res = client.get("/api/health/db")
    assert res.status_code == 503
    data = res.get_json()
    assert data["success"] is False
    assert data["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_auth_full_journey_with_revocation(client):
    phone = "9876543220"  # Raw 10-digit, must normalize to +919876543220

    # 1. Request OTP
    req_res = client.post(
        "/api/auth/request-otp",
        data=json.dumps({"phone": phone}),
        content_type="application/json"
    )
    assert req_res.status_code == 200
    req_json = req_res.get_json()
    assert req_json["success"] is True
    assert req_json["data"]["phone"] == "+919876543220"  # Normalized
    mock_otp = req_json["data"]["_mock_otp"]

    # 2. Verify OTP
    verify_res = client.post(
        "/api/auth/verify-otp",
        data=json.dumps({"phone": phone, "otp": mock_otp}),
        content_type="application/json"
    )
    assert verify_res.status_code == 200
    verify_json = verify_res.get_json()
    token = verify_json["data"]["token"]
    driver_id = verify_json["data"]["driver"]["driver_id"]
    assert token is not None

    # 3. Access Protected /api/auth/me with Bearer token (Before Logout -> Succeeded)
    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert me_res.status_code == 200
    me_json = me_res.get_json()
    assert me_json["data"]["driver_id"] == driver_id
    assert me_json["data"]["phone"] == "+919876543220"

    # 4. Access Protected /api/auth/me without token -> Must return 401
    unauth_res = client.get("/api/auth/me")
    assert unauth_res.status_code == 401
    assert unauth_res.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 5. Access with invalid token -> Must return 401
    invalid_res = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer bad-token-123"}
    )
    assert invalid_res.status_code == 401
    assert invalid_res.get_json()["error"]["code"] == "INVALID_TOKEN"

    # 6. Logout (Server-side revocation)
    logout_res = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert logout_res.status_code == 200
    assert logout_res.get_json()["success"] is True

    # 7. Access Protected /api/auth/me with the SAME token AFTER logout -> MUST BE REJECTED 401
    revoked_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked_res.status_code == 401
    revoked_json = revoked_res.get_json()
    assert revoked_json["error"]["code"] == "TOKEN_REVOKED"


def test_cross_driver_session_isolation(client):
    # Driver A
    phone_a = "+919876543221"
    req_a = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone_a}), content_type="application/json")
    otp_a = req_a.get_json()["data"]["_mock_otp"]
    ver_a = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone_a, "otp": otp_a}), content_type="application/json")
    token_a = ver_a.get_json()["data"]["token"]

    # Driver B
    phone_b = "+919876543222"
    req_b = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone_b}), content_type="application/json")
    otp_b = req_b.get_json()["data"]["_mock_otp"]
    ver_b = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone_b, "otp": otp_b}), content_type="application/json")
    token_b = ver_b.get_json()["data"]["token"]

    # Driver A logs out
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

    # Driver A's token must be revoked
    res_a = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a.status_code == 401
    assert res_a.get_json()["error"]["code"] == "TOKEN_REVOKED"

    # Driver B's token MUST REMAIN VALID!
    res_b = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200
    assert res_b.get_json()["data"]["phone"] == phone_b


def test_invalid_phone_rejection_at_api(client):
    # Short/Malformed number
    res = client.post(
        "/api/auth/request-otp",
        data=json.dumps({"phone": "12345"}),
        content_type="application/json"
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_PHONE"
