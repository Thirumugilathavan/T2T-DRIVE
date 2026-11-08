"""
API Integration Tests for Phase 5 Voice & Conversational Agent Journeys.
Tests multi-turn assistant queries in Tamil, Tanglish, and English for:
- Document expiry queries
- Unpaid challan queries
- Upcoming service schedule queries
- Maintenance expense recording with explicit confirmation
"""

import json
from decimal import Decimal
import pytest


def get_driver_token(client, phone="9876543901"):
    req_res = client.post("/api/auth/request-otp", data=json.dumps({"phone": phone}), content_type="application/json")
    mock_otp = req_res.get_json()["data"]["_mock_otp"]
    ver_res = client.post("/api/auth/verify-otp", data=json.dumps({"phone": phone, "otp": mock_otp}), content_type="application/json")
    data = ver_res.get_json()["data"]
    return data["token"], data["driver"]["driver_id"]


def test_agent_document_expiry_query_journey(client):
    token, driver_id = get_driver_token(client, "9876543902")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Register insurance expiring on 2026-12-25
    client.post(
        "/api/documents",
        headers=headers,
        data=json.dumps({
            "type": "Vehicle Insurance",
            "number": "POL-VOICE-88",
            "expiry": "2026-12-25",
            "vehicle_id": "TN-09-CB-1284"
        })
    )

    # 2. Driver asks via agent: "En insurance eppo expire aagum?"
    chat_res = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "En insurance eppo expire aagum?", "language": "tanglish"})
    )
    assert chat_res.status_code == 200
    data = chat_res.get_json()["data"]
    assert data["intent"] == "CHECK_DOCUMENT_EXPIRY"
    assert "2026-12-25" in data["message"]
    assert "expire" in data["message"].lower()


def test_agent_unpaid_challan_query_journey(client):
    token, driver_id = get_driver_token(client, "9876543903")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Add unpaid challan
    client.post(
        "/api/challans",
        headers=headers,
        data=json.dumps({
            "challan_number": "TN09VOICE99",
            "vehicle_id": "TN-09-CB-1284",
            "violation_description": "Over speed",
            "fine_amount": "500.00"
        })
    )

    # 2. Driver asks: "Enakku unpaid challan irukka?"
    chat_res = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "Enakku unpaid challan irukka?", "language": "tanglish"})
    )
    assert chat_res.status_code == 200
    data = chat_res.get_json()["data"]
    assert data["intent"] == "CHECK_UNPAID_CHALLANS"
    assert "500" in data["message"]


def test_agent_upcoming_service_query_journey(client):
    token, driver_id = get_driver_token(client, "9876543904")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Log service with upcoming schedule
    client.post(
        "/api/maintenance",
        headers=headers,
        data=json.dumps({
            "vehicle_id": "TN-09-CB-1284",
            "maintenance_category": "ENGINE_OIL",
            "description": "Oil service",
            "cost": "450.00",
            "next_service_date": "2026-12-20",
            "next_service_odometer": 68000
        })
    )

    # 2. Driver asks: "En auto ku service eppo?"
    chat_res = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "En auto ku service eppo?", "language": "tanglish"})
    )
    assert chat_res.status_code == 200
    data = chat_res.get_json()["data"]
    assert data["intent"] == "CHECK_UPCOMING_SERVICE"
    assert "2026-12-20" in data["message"]


def test_agent_maintenance_expense_proposal_and_confirmation(client):
    token, driver_id = get_driver_token(client, "9876543905")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Turn 1: Driver states maintenance expense: "Auto service ku 1200 rooba selavu aachu."
    res1 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"message": "Auto service ku 1200 rooba selavu aachu.", "language": "tanglish"})
    )
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    assert data1["next_step"] == "AWAITING_CONFIRMATION"
    pending_id = data1["pending_id"]
    assert pending_id.startswith("PEND_")
    assert "1200" in data1["message"]
    session_id = data1["session_id"]

    # Turn 2: Driver confirms: "Aama confirm pannu"
    res2 = client.post(
        "/api/agent/chat",
        headers=headers,
        data=json.dumps({"session_id": session_id, "message": "Aama confirm pannu", "language": "tanglish"})
    )
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert data2["next_step"] == "COMPLETED"
    assert "vetrikaramaga" in data2["message"] or "recorded" in data2["message"].lower() or "வெற்றிகரமாக" in data2["message"]

    # Verify maintenance record exists in maintenance service
    maint_res = client.get("/api/maintenance", headers=headers)
    assert maint_res.status_code == 200
    m_records = maint_res.get_json()["data"]["maintenance_records"]
    assert len(m_records) >= 1
    assert any(Decimal(r["cost"]) == Decimal("1200.00") for r in m_records)
