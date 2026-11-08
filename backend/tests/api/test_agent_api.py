"""
API Integration tests for T2T DRIVE Conversational Agent & LangGraph State Machine.
Tests conversational chat endpoints with JWT authentication, multilingual intent processing,
confirmation firewall enforcement, slot filling, and cross-driver isolation.
"""

import json
import pytest
from app.agent.nlu import AgentIntent


def get_driver_token(client, phone="9876543401"):
    """Helper to authenticate a driver and retrieve JWT bearer token."""
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_agent_unauthenticated_access_rejected(client):
    res = client.post("/api/agent/chat", data=json.dumps({"message": "diesel 400"}), content_type="application/json")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_agent_propose_confirm_conversational_journey(client):
    """
    Validates complete two-turn conversational transaction flow:
    Turn 1: Propose expense via natural voice/text -> Agent returns confirmation prompt, ledger remains empty.
    Turn 2: Affirm with 'aama confirm' -> Agent commits write to append-only ledger atomically.
    """
    token, driver_id = get_driver_token(client, "9876543402")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    db = client.application.extensions["db"]

    # Turn 1: Driver says "diesel 400 potten"
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "diesel 400 potten", "language": "tanglish"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    session_id = data1["session_id"]

    assert data1["intent"] == AgentIntent.RECORD_EXPENSE
    assert data1["next_step"] == "AWAITING_CONFIRMATION"
    assert "active_pending_action" in data1
    assert data1["active_pending_action"] is not None
    pending_id = data1["active_pending_action"]["pending_action_id"]

    # STRICT FIREWALL CHECK: Transaction ledger MUST BE EMPTY at this stage!
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Turn 2: Driver affirms "aama confirm"
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "aama confirm", "language": "tanglish"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]

    assert data2["next_step"] == "COMPLETED"
    assert data2["active_pending_action"] is None
    assert "vetrikaramaga" in data2["message"].lower() or "done" in data2["message"].lower()

    # LEDGER CHECK: Exactly 1 transaction must now exist in the ledger!
    ledger_records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(ledger_records) == 1
    txn = ledger_records[0]
    assert txn["category"] == "FUEL"
    assert str(txn["signed_amount"]) == "-400.00"
    assert txn["driver_id"] == driver_id


def test_agent_cancellation_flow(client):
    """
    Validates cancellation flow:
    Driver proposes an income action, then rejects with 'vendaam cancel'.
    Verifies that ledger is not written and pending action is marked CANCELLED.
    """
    token, driver_id = get_driver_token(client, "9876543403")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    db = client.application.extensions["db"]

    # Turn 1: Propose income
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "savari 800 aachu", "language": "tanglish"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    session_id = data1["session_id"]
    pending_id = data1["active_pending_action"]["pending_action_id"]

    # Turn 2: Cancel
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "vendaam cancel", "language": "tanglish"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]

    assert data2["next_step"] == "IDLE"
    assert data2["active_pending_action"] is None
    assert "cancel" in data2["message"].lower()

    # Ledger remains 0 records
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Pending action document is CANCELLED
    pending_doc = db.pending_actions.find_one({"pending_action_id": pending_id})
    assert pending_doc["status"] == "CANCELLED"


def test_agent_slot_filling_flow(client):
    """
    Validates missing slot clarification:
    Turn 1: Driver says "tea tiffin" (no amount) -> Agent asks for amount.
    Turn 2: Driver says "50" -> Agent creates proposal with amount 50.
    Turn 3: Driver confirms -> Transaction is recorded in ledger.
    """
    token, driver_id = get_driver_token(client, "9876543404")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    db = client.application.extensions["db"]

    # Turn 1: Missing amount
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "tiffin sappadu", "language": "tanglish"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    session_id = data1["session_id"]

    assert data1["next_step"] == "AWAITING_SLOT"
    assert "Food" in data1["message"] or "food" in data1["message"].lower()

    # Turn 2: Provide amount
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "50", "language": "tanglish"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]

    assert data2["next_step"] == "AWAITING_CONFIRMATION"
    assert data2["active_pending_action"] is not None
    assert data2["slots"]["amount"] == 50.0

    # Turn 3: Confirm
    res3 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "confirm", "language": "tanglish"})
    )
    assert res3.status_code == 200
    data3 = res3.get_json()["data"]
    assert data3["next_step"] == "COMPLETED"

    # Ledger check
    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["category"] == "FOOD"
    assert str(records[0]["signed_amount"]) == "-50.00"


def test_agent_summary_and_help_queries(client):
    """Validates summary report and help queries."""
    token, driver_id = get_driver_token(client, "9876543405")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Query summary
    res_sum = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "inniku kanaku sollu", "language": "tanglish"})
    )
    assert res_sum.status_code == 200
    sum_data = res_sum.get_json()["data"]
    assert sum_data["intent"] == AgentIntent.GET_SUMMARY
    assert "Varumanam" in sum_data["message"] or "Income" in sum_data["message"]

    # Query help
    res_help = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "help", "language": "tanglish"})
    )
    assert res_help.status_code == 200
    help_data = res_help.get_json()["data"]
    assert help_data["intent"] == AgentIntent.HELP
    assert "Voice Co-Pilot" in help_data["message"]


def test_agent_cross_driver_session_isolation(client):
    """
    Validates that Driver B cannot read or modify Driver A's conversation session.
    """
    token_a, driver_a = get_driver_token(client, "9876543406")
    token_b, driver_b = get_driver_token(client, "9876543407")

    headers_a = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}
    headers_b = {"Authorization": f"Bearer {token_b}", "Content-Type": "application/json"}

    # Driver A starts a session
    sess_res = client.post("/api/agent/sessions", headers=headers_a, data=json.dumps({}))
    assert sess_res.status_code == 201
    session_id = sess_res.get_json()["data"]["session_id"]

    # Driver A chats in the session
    client.post(
        "/api/agent/chat",
        headers=headers_a,
        data=json.dumps({"session_id": session_id, "message": "diesel 300"})
    )

    # Driver B attempts to read Driver A's session -> must be rejected with 403 Forbidden!
    snoop_res = client.get(f"/api/agent/sessions/{session_id}", headers=headers_b)
    assert snoop_res.status_code == 403
    assert snoop_res.get_json()["error"]["code"] == "UNAUTHORIZED_SESSION"


def test_agent_sessions_list_and_history(client):
    """Tests listing sessions and reading conversation messages."""
    token, driver_id = get_driver_token(client, "9876543408")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Start chat
    res = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "help", "language": "tanglish"})
    )
    assert res.status_code == 200
    session_id = res.get_json()["data"]["session_id"]

    # List sessions
    list_res = client.get("/api/agent/sessions", headers=headers)
    assert list_res.status_code == 200
    sessions = list_res.get_json()["data"]
    assert len(sessions) >= 1
    assert any(s["session_id"] == session_id for s in sessions)

    # Get session details & history
    detail_res = client.get(f"/api/agent/sessions/{session_id}", headers=headers)
    assert detail_res.status_code == 200
    detail_data = detail_res.get_json()["data"]
    assert detail_data["session"]["session_id"] == session_id
    messages = detail_data["messages"]
    assert len(messages) >= 2  # Driver message and Agent message
    assert messages[0]["sender"] == "DRIVER"
    assert messages[1]["sender"] == "AGENT"


def test_agent_owner_payment_flow(client):
    """Tests owner payment proposal and confirmation via conversational agent."""
    token, driver_id = get_driver_token(client, "9876543409")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    db = client.application.extensions["db"]

    # Turn 1: Propose owner payment
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "ownerukku 350 kuduthen", "language": "tanglish"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    assert data1["intent"] == AgentIntent.RECORD_OWNER_PAYMENT
    session_id = data1["session_id"]

    # Turn 2: Confirm
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "sari confirm", "language": "tanglish"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert data2["next_step"] == "COMPLETED"

    # Ledger check
    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["transaction_type"] == "OWNER_PAYMENT"
    assert str(records[0]["signed_amount"]) == "-350.00"


def test_agent_multilingual_tamil_script_journey(client):
    """Tests complete flow conducted entirely in pure Tamil script."""
    token, driver_id = get_driver_token(client, "9876543410")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    db = client.application.extensions["db"]

    # Turn 1: Tamil expense proposal
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "டீசல் 500 போட்டேன்", "language": "tamil"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    assert data1["intent"] == AgentIntent.RECORD_EXPENSE
    assert data1["language"] == "tamil"
    session_id = data1["session_id"]

    # Turn 2: Tamil confirmation
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "ஆம் உறுதி செய்", "language": "tamil"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert data2["next_step"] == "COMPLETED"

    # Ledger check
    records = list(db.transactions.find({"driver_id": driver_id}))
    assert len(records) == 1
    assert records[0]["category"] == "FUEL"
    assert str(records[0]["signed_amount"]) == "-500.00"
