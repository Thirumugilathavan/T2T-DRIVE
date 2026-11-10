"""
Unit and Integration Tests for AI Extraction Provider Authentication & Bearer Header Enforcement.
Validates:
1. RFC 6750 Bearer Authorization header construction.
2. Token whitespace and quote sanitization.
3. Missing token rejection.
4. Malformed token rejection.
5. Upstream AI provider HTTP 401 error handling without secret leakage.
6. Successful AI extraction response parsing.
7. Strict prohibition of silent mock fallback in live mode.
8. Demo-session JWT token issuance and seamless /api/agent/message authentication.
"""

import json
import pytest
import httpx
from app.agent.llm_adapter import clean_bearer_token, build_bearer_header, LLMAdapter


# ============================================================================
# 1. BEARER HEADER CONSTRUCTION & TOKEN SANITIZATION TESTS
# ============================================================================

def test_bearer_header_correct_construction():
    """Verifies that clean tokens produce standard 'Bearer <token>' format."""
    header = build_bearer_header("test_secret_token_abc123")
    assert header == {"Authorization": "Bearer test_secret_token_abc123"}


def test_bearer_header_whitespace_trimming():
    """Verifies that leading and trailing whitespace are trimmed."""
    header = build_bearer_header("   token_with_spaces_xyz   ")
    assert header == {"Authorization": "Bearer token_with_spaces_xyz"}


def test_bearer_header_quotes_stripping():
    """Verifies that accidental double or single quotes from config files are stripped."""
    # Double quotes
    h_double = build_bearer_header('"token_inside_quotes"')
    assert h_double == {"Authorization": "Bearer token_inside_quotes"}

    # Single quotes
    h_single = build_bearer_header("'token_inside_single_quotes'")
    assert h_single == {"Authorization": "Bearer token_inside_single_quotes"}

    # Mixed whitespace and quotes
    h_mixed = build_bearer_header('  "  token_nested  "  ')
    assert h_mixed == {"Authorization": "Bearer token_nested"}


# ============================================================================
# 2. MISSING & MALFORMED TOKEN TESTS
# ============================================================================

def test_missing_token_rejection():
    """Verifies that None or empty strings are rejected with ValueError."""
    with pytest.raises(ValueError, match="missing"):
        clean_bearer_token(None)

    with pytest.raises(ValueError, match="missing"):
        build_bearer_header(None)

    with pytest.raises(ValueError, match="missing or malformed"):
        clean_bearer_token("")

    with pytest.raises(ValueError, match="missing or malformed"):
        build_bearer_header("")


def test_malformed_token_rejection():
    """Verifies that whitespace-only or quotes-only tokens are rejected as malformed."""
    with pytest.raises(ValueError, match="missing or malformed"):
        clean_bearer_token("     ")

    with pytest.raises(ValueError, match="missing or malformed"):
        build_bearer_header("   \t\n   ")

    with pytest.raises(ValueError, match="missing or malformed"):
        clean_bearer_token('""')

    with pytest.raises(ValueError, match="missing or malformed"):
        clean_bearer_token("''")

    with pytest.raises(ValueError, match="missing or malformed"):
        clean_bearer_token('  ""  ')


# ============================================================================
# 3. UPSTREAM PROVIDER HTTP 401 & RESPONSE HANDLING
# ============================================================================

class Dummy401Response:
    status_code = 401
    text = '{"error": {"message": "Invalid Bearer Token", "type": "invalid_request_error"}}'

    def json(self):
        return {"error": {"message": "Invalid Bearer Token"}}


class Dummy200Response:
    status_code = 200

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "intent": "RECORD_EXPENSE",
                            "amount": 400.0,
                            "category": "FUEL",
                            "language": "tanglish"
                        })
                    }
                }
            ]
        }


def test_provider_http_401_response(monkeypatch):
    """
    Simulates upstream AI provider rejecting credentials with HTTP 401.
    Verifies adapter raises PermissionError and does not leak the secret token.
    """
    secret = "secret_test_key_999"
    adapter = LLMAdapter(api_key=secret, inference_url="https://mock-ai.test/v1/chat/completions")

    def mock_post(*args, **kwargs):
        # Assert the header was properly sent server-side
        sent_headers = kwargs.get("headers", {})
        assert sent_headers.get("Authorization") == f"Bearer {secret}"
        return Dummy401Response()

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    with pytest.raises(PermissionError) as exc_info:
        adapter.extract_intent_and_entities("diesel 400", require_live=True)

    err_msg = str(exc_info.value)
    assert "HTTP 401 Unauthorized" in err_msg
    assert "Check LLM_API_KEY" in err_msg
    # Ensure the actual secret key is NOT present in the exception message
    assert secret not in err_msg


def test_successful_extraction_response(monkeypatch):
    """Verifies that HTTP 200 response from AI provider is parsed correctly."""
    adapter = LLMAdapter(api_key="valid_token_123", inference_url="https://mock-ai.test/v1/chat/completions")

    def mock_post(*args, **kwargs):
        return Dummy200Response()

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = adapter.extract_intent_and_entities("diesel 400", require_live=True)
    assert result is not None
    assert result.get("intent") == "RECORD_EXPENSE"
    assert result.get("amount") == 400.0
    assert result.get("category") == "FUEL"


def test_no_silent_mock_fallback_in_live_mode():
    """
    Verifies that when require_live=True is passed, missing configuration
    strictly raises an error rather than silently returning mock data.
    """
    unconfigured_adapter = LLMAdapter(api_key="")
    with pytest.raises(ValueError, match="LLM_API_KEY is missing"):
        unconfigured_adapter.extract_intent_and_entities("diesel 400", require_live=True)


# ============================================================================
# 4. FLASK DEMO SESSION & LIVE /api/agent/message AUTHENTICATION
# ============================================================================

def test_demo_session_endpoint_issues_valid_jwt(client):
    """
    Verifies that POST /api/auth/demo-session issues a valid signed JWT
    restricted to DRV_DEMO_GUEST that can authenticate directly against /api/agent/message.
    """
    res = client.post("/api/auth/demo-session")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "token" in data
    assert data.get("is_demo") is True
    assert data["driver"]["driver_id"] == "DRV_DEMO_GUEST"
    token = data["token"]
    assert len(token) > 20

    # Call /api/agent/message with this Bearer token
    agent_res = client.post(
        "/api/agent/message",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"text": "diesel 400", "session": "test-session-1"})
    )
    assert agent_res.status_code == 200
    agent_data = agent_res.get_json()["data"]
    assert agent_data["intent"] == "RECORD_EXPENSE"
    assert agent_data["active_pending_action"] is not None


def test_demo_guest_financial_writes_are_blocked(client):
    """
    Verifies that confirming a financial action with a demo guest token simulates
    the execution result and NEVER writes a real transaction to the financial ledger.
    """
    auth_res = client.post("/api/auth/demo-session")
    assert auth_res.status_code == 200
    token = auth_res.get_json()["data"]["token"]

    # 1. Propose action via conversational agent
    msg_res = client.post(
        "/api/agent/message",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"text": "diesel 500", "session": "demo-guard-test"})
    )
    assert msg_res.status_code == 200
    action = msg_res.get_json()["data"]["active_pending_action"]
    assert action is not None
    pending_id = action["pending_action_id"]

    # 2. Count current ledger transactions in db
    db = client.application.extensions["db"]
    initial_txn_count = db.transactions.count_documents({"driver_id": "DRV_DEMO_GUEST"})

    # 3. Confirm action via /api/agent/confirm
    confirm_res = client.post(
        "/api/agent/confirm",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"pending_id": pending_id, "yes_or_no": True})
    )
    assert confirm_res.status_code == 200
    exec_result = confirm_res.get_json()["data"]
    assert exec_result["status"] == "SIMULATED"
    assert exec_result.get("is_demo") is True

    # 4. Verify no real transaction was committed to the database ledger
    after_txn_count = db.transactions.count_documents({"driver_id": "DRV_DEMO_GUEST"})
    assert after_txn_count == initial_txn_count == 0


def test_structured_health_endpoint(client):
    """
    Verifies that GET /api/health returns the structured schema with status,
    database, and provider states.
    """
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["status"] == "UP"
    assert data["service"] == "T2T DRIVE Backend"
    assert "environment" in data
    assert "database" in data
    assert "connected" in data["database"]
    assert "providers" in data
    assert "gnani_prisma" in data["providers"]
    assert "gnani_timbre" in data["providers"]
    assert "llm_adapter" in data["providers"]


def test_agent_message_missing_bearer_rejected(client):
    """
    Verifies that unauthenticated calls to /api/agent/message are rejected with
    the exact error message observed in production.
    """
    res = client.post(
        "/api/agent/message",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"text": "diesel 400", "session": "test-session-1"})
    )
    assert res.status_code == 401
    err = res.get_json()["error"]
    assert err["code"] == "UNAUTHORIZED"
    assert err["message"] == "Missing or malformed Authorization header. Expected 'Bearer <token>'."
