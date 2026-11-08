"""
API Integration tests for T2T DRIVE Core Financial Engine.
Tests all financial endpoints with cryptographic JWT authentication,
pending action confirmations, cross-driver isolation, summaries, and settlements.
"""

import json
import pytest


def get_driver_token(client, phone="9876543301"):
    """Helper to authenticate a driver and retrieve JWT bearer token."""
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_transaction_propose_confirm_journey(client):
    token, driver_id = get_driver_token(client, "9876543302")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Propose Expense of ₹450
    prop_res = client.post(
        "/api/transactions/propose",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "KA01AB9999",
            "transaction_type": "EXPENSE",
            "amount": "450.00",
            "category": "FUEL",
            "description": "CNG refill",
            "idempotency_key": "API_KEY_PROP_1"
        })
    )
    assert prop_res.status_code == 201
    prop_data = prop_res.get_json()["data"]
    pending_id = prop_data["pending_action_id"]
    assert prop_data["status"] == "PENDING"
    assert "Confirm recording expense" in prop_data["human_readable_summary"]

    # 2. Confirm Expense
    conf_res = client.post(
        f"/api/transactions/{pending_id}/confirm",
        headers=headers,
        data=json.dumps({"idempotency_key": "API_KEY_CONF_1"})
    )
    assert conf_res.status_code == 200
    conf_data = conf_res.get_json()["data"]
    txn_id = conf_data["transaction_id"]
    assert conf_data["amount"] == "450.00"
    assert conf_data["signed_amount"] == "-450.00"

    # 3. List Transactions
    list_res = client.get("/api/transactions", headers=headers)
    assert list_res.status_code == 200
    list_data = list_res.get_json()["data"]
    assert len(list_data["transactions"]) >= 1
    assert any(t["transaction_id"] == txn_id for t in list_data["transactions"])

    # 4. Get Transaction By ID
    get_res = client.get(f"/api/transactions/{txn_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.get_json()["data"]["transaction_id"] == txn_id


def test_unauthenticated_financial_access_rejected(client):
    # Missing Bearer token must return 401 UNAUTHORIZED
    res = client.post(
        "/api/transactions/propose",
        data=json.dumps({"vehicle_id": "KA01", "transaction_type": "INCOME", "amount": "100", "idempotency_key": "K"}),
        content_type="application/json"
    )
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_cross_driver_financial_isolation(client):
    token_a, driver_a = get_driver_token(client, "9876543303")
    token_b, driver_b = get_driver_token(client, "9876543304")

    headers_a = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}
    headers_b = {"Authorization": f"Bearer {token_b}", "Content-Type": "application/json"}

    # Driver A proposes an action
    prop_res = client.post(
        "/api/transactions/propose",
        headers=headers_a,
        data=json.dumps({
            "vehicle_id": "KA01AB1111",
            "transaction_type": "INCOME",
            "amount": "1000.00",
            "category": "FARE",
            "idempotency_key": "ALICE_KEY"
        })
    )
    pending_id_a = prop_res.get_json()["data"]["pending_action_id"]

    # Driver B attempts to confirm Driver A's pending action -> 403 FORBIDDEN!
    bad_conf = client.post(
        f"/api/transactions/{pending_id_a}/confirm",
        headers=headers_b,
        data=json.dumps({"idempotency_key": "BOB_ATTACK_KEY"})
    )
    assert bad_conf.status_code == 403
    assert bad_conf.get_json()["error"]["code"] == "UNAUTHORIZED_FINANCIAL_ACCESS"


def test_daily_summary_and_audit_api(client):
    token, driver_id = get_driver_token(client, "9876543305")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Record Income via propose -> confirm
    p1 = client.post("/api/transactions/propose", headers=headers, data=json.dumps({
        "vehicle_id": "KA01CD2222", "transaction_type": "INCOME", "amount": "1500.00", "category": "FARE", "idempotency_key": "S_P1"
    }))
    client.post(f"/api/transactions/{p1.get_json()['data']['pending_action_id']}/confirm", headers=headers, data=json.dumps({"idempotency_key": "S_C1"}))

    # Record Expense
    p2 = client.post("/api/transactions/propose", headers=headers, data=json.dumps({
        "vehicle_id": "KA01CD2222", "transaction_type": "EXPENSE", "amount": "400.00", "category": "FUEL", "idempotency_key": "S_P2"
    }))
    client.post(f"/api/transactions/{p2.get_json()['data']['pending_action_id']}/confirm", headers=headers, data=json.dumps({"idempotency_key": "S_C2"}))

    # Fetch daily summary
    summ_res = client.get("/api/finance/summary/daily", headers=headers)
    assert summ_res.status_code == 200
    m = summ_res.get_json()["data"]["metrics"]
    assert m["gross_income"] == "1500.00"
    assert m["operating_expenses"] == "400.00"
    assert m["operating_profit"] == "1100.00"

    # Fetch audit log
    audit_res = client.get("/api/finance/audit", headers=headers)
    assert audit_res.status_code == 200
    audit_data = audit_res.get_json()["data"]["audit_logs"]
    assert len(audit_data) >= 2


def test_settlement_api_flow(client):
    token, driver_id = get_driver_token(client, "9876543306")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Propose settlement
    prop_res = client.post(
        "/api/settlements/propose",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "KA01EF3333",
            "previous_balance": "100.00",
            "idempotency_key": "SETTLE_PROP_API_1"
        })
    )
    assert prop_res.status_code == 201
    pending_id = prop_res.get_json()["data"]["pending_action_id"]

    # Confirm settlement
    conf_res = client.post(
        f"/api/settlements/{pending_id}/confirm",
        headers=headers,
        data=json.dumps({"idempotency_key": "SETTLE_CONF_API_1"})
    )
    assert conf_res.status_code == 200
    s_data = conf_res.get_json()["data"]
    assert "settlement_id" in s_data
    assert s_data["version"] == 1
    assert "remaining_balance" in s_data
