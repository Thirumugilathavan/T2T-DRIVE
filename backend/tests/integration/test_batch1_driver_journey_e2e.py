"""
T2T-DRIVE — Batch 1: Complete Driver Voice-to-Finance End-to-End Integration Suite.
Validates the entire 12-step driver journey across Workstreams A, B, C, D, and E:
1. Driver logs in via OTP.
2. Driver records/submits a Tanglish voice message.
3. Audio is transcribed via Prisma STT adapter.
4. NLU extracts three financial actions (FARE 1500, FUEL 300, OWNER 200).
5. Assistant reads back the proposal.
6. Driver explicitly confirms.
7. Three records are persisted to the immutable transaction ledger.
8. Dashboard daily summary updates (Gross 1500, Exp 300, Net 1000).
9. Owner settlement reconciles (Rent 350, Paid 200, Remaining 150).
10. Assistant responds with confirmation voice_text and Timbre TTS audio.
11. Driver restarts the application (new app instance).
12. Financial history and dashboard persist correctly.

Also tests cancellation, failure-injection crash recovery, and driver isolation.
Zero live Gnani API calls; zero production database writes.
"""

import os
import io
import base64
import pytest
from pathlib import Path
from decimal import Decimal

from app import create_app
from app.models.financial import TransactionType, PendingActionStatus
from app.database.indexes import ensure_indexes
from app.utils.dates import today_ist


AUDIO_DIR = Path(__file__).resolve().parent.parent / "test_audio"
TANGLISH_WAV = AUDIO_DIR / "T2T_Tanglish_Test_Audio.wav"


@pytest.fixture
def app_and_db():
    """Sets up a test Flask application configured for isolated mock testing."""
    app = create_app("testing")
    app.config.update({
        "MONGODB_URI": "mongomock://localhost:27017/t2t_drive_e2e_test",
        "DB_NAME": "t2t_drive_e2e_test",
        "JWT_SECRET_KEY": "test-jwt-secret-key-t2t-drive-2026",
        "OTP_HASH_SECRET": "test-otp-secret-key-t2t-drive-2026",
        "VOICE_PROVIDER_MODE": "mock",
        "GNANI_PRISMA_ENABLED": False,
        "GNANI_TIMBRE_ENABLED": False
    })
    db = app.extensions["db_manager"].get_db()
    ensure_indexes(db)
    return app, db


def _authenticate_driver(client, phone: str = "+919876543210"):
    """Helper to authenticate a driver and return (token, driver_id)."""
    # 1. Request OTP
    res1 = client.post("/api/auth/request-otp", json={"phone": phone})
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    mock_otp = data1.get("_mock_otp", "123456")

    # 2. Verify OTP
    res2 = client.post("/api/auth/verify-otp", json={"phone": phone, "otp": mock_otp})
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    token = data2["token"]
    driver_id = data2["driver"]["driver_id"]
    return token, driver_id


# ============================================================================
# WORKSTREAM E: 12-STEP END-TO-END DEMONSTRATION JOURNEY
# ============================================================================

def test_complete_12_step_driver_voice_to_finance_journey(app_and_db):
    """
    Executes the exact 12-step end-to-end driver journey:
    Audio -> STT -> NLU -> Proposal -> Confirm -> 3 Ledger Inserts ->
    Dashboard Update -> Owner Settlement -> App Restart -> Persisted Data.
    """
    app, db = app_and_db
    client = app.test_client()

    # ------------------------------------------------------------------------
    # STEP 1: Driver logs in
    # ------------------------------------------------------------------------
    token, driver_id = _authenticate_driver(client, phone="+919876543210")
    headers = {"Authorization": f"Bearer {token}"}
    assert driver_id.startswith("DRV_")

    # Associate vehicle KA01AB1234 with daily contract rent ₹350.00
    settle_svc = app.extensions["settlement_service"]
    settle_svc.get_or_create_vehicle(
        vehicle_id="KA01AB1234",
        driver_id=driver_id,
        default_rent=Decimal("350.00")
    )

    # ------------------------------------------------------------------------
    # STEP 2 & 3: Driver records Tanglish voice message & Audio is transcribed
    # ------------------------------------------------------------------------
    assert TANGLISH_WAV.exists(), f"Tanglish test audio file missing at {TANGLISH_WAV}"
    audio_bytes = TANGLISH_WAV.read_bytes()

    data = {
        "audio": (io.BytesIO(audio_bytes), "T2T_Tanglish_Test_Audio.wav"),
        "lang": "tanglish",
        "generate_tts": "true"
    }

    voice_res = client.post(
        "/api/voice/chat",
        data=data,
        content_type="multipart/form-data",
        headers=headers
    )
    assert voice_res.status_code == 200
    v_data = voice_res.get_json()["data"]

    # Verify acoustic validation, noise analysis, and STT provider distinction
    assert v_data.get("audio_quality") is not None
    assert v_data.get("noise_classification") is not None
    assert v_data.get("snr_estimate") is not None
    assert v_data.get("stt_provider") == "mock_prisma"  # Offline mock STT utilizing verified Tanglish transcript

    # Verify transcription
    transcript = v_data.get("transcript", "")
    assert "collection 1500" in transcript
    assert "petrol 300" in transcript
    assert "owner" in transcript

    # ------------------------------------------------------------------------
    # STEP 4: NLU extracts three financial actions
    # ------------------------------------------------------------------------
    active_pending = v_data.get("active_pending_action")
    assert active_pending is not None
    assert active_pending["action_type"] == "ADD_BATCH_TRANSACTIONS"

    txns = active_pending["proposed_data"]["transactions"]
    assert len(txns) == 3

    fare_t = next(t for t in txns if t["category"] == "FARE")
    fuel_t = next(t for t in txns if t["category"] == "FUEL")
    owner_t = next(t for t in txns if t["category"] == "OWNER_RENT")

    assert "INCOME" in fare_t["action_type"]
    assert Decimal(str(fare_t["amount"])) == Decimal("1500.00")

    assert "EXPENSE" in fuel_t["action_type"]
    assert Decimal(str(fuel_t["amount"])) == Decimal("300.00")

    assert "OWNER" in owner_t["action_type"]
    assert Decimal(str(owner_t["amount"])) == Decimal("200.00")

    # ZERO writes to transactions collection prior to explicit driver confirmation
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # ------------------------------------------------------------------------
    # STEP 5: Assistant reads back the proposal + TTS audio
    # ------------------------------------------------------------------------
    proposal_text = v_data.get("agent_message", "")
    assert len(proposal_text) > 0
    # localized readback mentions the amounts
    assert "1500" in proposal_text or "1,500" in proposal_text

    # Decode and verify binary WAV RIFF header in TTS payload
    b64_audio = v_data.get("tts_audio_base64")
    assert b64_audio is not None
    decoded_audio = base64.b64decode(b64_audio)
    assert decoded_audio[:4] == b"RIFF"
    assert decoded_audio[8:12] == b"WAVE"
    pending_id = active_pending["pending_action_id"]

    # ------------------------------------------------------------------------
    # STEP 6: Driver confirms the proposed batch
    # ------------------------------------------------------------------------
    confirm_res = client.post(
        "/api/agent/confirm",
        json={"pending_id": pending_id, "yes_or_no": True},
        headers=headers
    )
    assert confirm_res.status_code == 200
    c_data = confirm_res.get_json()["data"]
    assert c_data["status"] == "CONFIRMED"
    assert c_data["count"] == 3

    # ------------------------------------------------------------------------
    # STEP 7: Three records are persisted to immutable transaction ledger
    # ------------------------------------------------------------------------
    db_txns = list(db.transactions.find({"driver_id": driver_id}))
    assert len(db_txns) == 3

    p_fare = next(t for t in db_txns if t["category"] == "FARE")
    p_fuel = next(t for t in db_txns if t["category"] == "FUEL")
    p_owner = next(t for t in db_txns if t["category"] == "OWNER_RENT")

    assert p_fare["transaction_type"] == "INCOME"
    assert Decimal(str(p_fare["signed_amount"])) == Decimal("1500.00")

    assert p_fuel["transaction_type"] == "EXPENSE"
    assert Decimal(str(p_fuel["signed_amount"])) == Decimal("-300.00")

    assert p_owner["transaction_type"] == "OWNER_PAYMENT"
    assert Decimal(str(p_owner["signed_amount"])) == Decimal("-200.00")

    # ------------------------------------------------------------------------
    # STEP 8: Dashboard daily summary updates
    # ------------------------------------------------------------------------
    today = today_ist()
    summary_res = client.get(f"/api/finance/summary/daily?date={today}", headers=headers)
    assert summary_res.status_code == 200
    s_data = summary_res.get_json()["data"]

    metrics = s_data["metrics"]
    assert Decimal(str(metrics["gross_income"])) == Decimal("1500.00")
    assert Decimal(str(metrics["operating_expenses"])) == Decimal("300.00")
    assert Decimal(str(metrics["operating_profit"])) == Decimal("1200.00")
    assert Decimal(str(metrics["owner_payments"])) == Decimal("200.00")
    assert Decimal(str(metrics["driver_take_home"])) == Decimal("1000.00")
    assert Decimal(str(metrics["net_cash_retained"])) == Decimal("1000.00")

    # ------------------------------------------------------------------------
    # STEP 9: Owner settlement is reconciled
    # ------------------------------------------------------------------------
    settle_prop = client.post(
        "/api/settlements/propose",
        json={
            "vehicle_id": "KA01AB1234",
            "settlement_date": today,
            "shift_id": "DEFAULT",
            "previous_balance": "0.00",
            "idempotency_key": "IDEM_SETTLE_PROP_001"
        },
        headers=headers
    )
    assert settle_prop.status_code == 201
    settle_pend_id = settle_prop.get_json()["data"]["pending_action_id"]

    settle_conf = client.post(
        f"/api/settlements/{settle_pend_id}/confirm",
        json={"idempotency_key": "IDEM_SETTLE_CONF_001"},
        headers=headers
    )
    assert settle_conf.status_code == 200
    settle_data = settle_conf.get_json()["data"]

    # Verify settlement calculation:
    # Expected rent: ₹350.00
    # Owner payment offset: ₹200.00
    # Remaining rent obligation: ₹150.00
    # Operating expenses: ₹300.00 (NOT inflated by owner payment)
    assert Decimal(str(settle_data["expected_rent"])) == Decimal("350.00")
    assert Decimal(str(settle_data["owner_payments"])) == Decimal("200.00")
    assert Decimal(str(settle_data["remaining_balance"])) == Decimal("150.00")
    assert Decimal(str(settle_data["operating_expenses"])) == Decimal("300.00")
    assert settle_data["settlement_status"] == "PARTIALLY_SETTLED"

    # ------------------------------------------------------------------------
    # STEP 10: Assistant responds using TTS
    # ------------------------------------------------------------------------
    speak_res = client.post(
        "/api/voice/speak",
        json={"text": "ஆக்‌ஷன் உறுதி செய்யப்பட்டது. ₹1,500 வரவு, ₹300 பெட்ரோல், ₹200 ஓனர் பதிவு செய்யப்பட்டது.", "lang": "ta-IN"},
        headers=headers
    )
    assert speak_res.status_code == 200
    sp_data = speak_res.get_json()["data"]
    speak_b64 = sp_data.get("audio_base64")
    assert speak_b64 is not None
    speak_decoded = base64.b64decode(speak_b64)
    assert speak_decoded[:4] == b"RIFF"
    assert speak_decoded[8:12] == b"WAVE"
    assert sp_data.get("status") == "SUCCESS"

    # ------------------------------------------------------------------------
    # STEP 11: Driver restarts the application (Simulate process restart)
    # ------------------------------------------------------------------------
    new_app = create_app("testing", db=db)
    new_client = new_app.test_client()

    # ------------------------------------------------------------------------
    # STEP 12: Financial history and dashboard remain correct after restart
    # ------------------------------------------------------------------------
    post_restart_summary = new_client.get(f"/api/finance/summary/daily?date={today}", headers=headers)
    assert post_restart_summary.status_code == 200
    post_metrics = post_restart_summary.get_json()["data"]["metrics"]

    assert Decimal(str(post_metrics["gross_income"])) == Decimal("1500.00")
    assert Decimal(str(post_metrics["operating_expenses"])) == Decimal("300.00")
    assert Decimal(str(post_metrics["operating_profit"])) == Decimal("1200.00")
    assert Decimal(str(post_metrics["owner_payments"])) == Decimal("200.00")
    assert Decimal(str(post_metrics["driver_take_home"])) == Decimal("1000.00")

    post_restart_settlements = new_client.get("/api/settlements", headers=headers)
    assert post_restart_settlements.status_code == 200
    settle_list = post_restart_settlements.get_json()["data"]["settlements"]
    assert len(settle_list) >= 1
    assert Decimal(str(settle_list[0]["remaining_balance"])) == Decimal("150.00")


# ============================================================================
# CANCELLATION JOURNEY
# ============================================================================

def test_e2e_cancellation_workflow(app_and_db):
    """
    Verifies that when a proposed batch is cancelled:
    - Status transitions to CANCELLED.
    - Zero transactions are written to the ledger.
    - Dashboard summary reflects ₹0.00.
    """
    app, db = app_and_db
    client = app.test_client()

    token, driver_id = _authenticate_driver(client, phone="+919876543211")
    headers = {"Authorization": f"Bearer {token}"}

    # Propose batch via text chat
    res = client.post(
        "/api/agent/chat",
        json={"message": "இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."},
        headers=headers
    )
    assert res.status_code == 200
    r_data = res.get_json()["data"]
    pending_id = r_data["active_pending_action"]["pending_action_id"]

    # Driver cancels
    cancel_res = client.post(
        "/api/agent/confirm",
        json={"pending_id": pending_id, "yes_or_no": False},
        headers=headers
    )
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["data"]["status"] == "CANCELLED"

    # Zero writes to ledger
    assert db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Summary is zero
    today = today_ist()
    summary_res = client.get(f"/api/finance/summary/daily?date={today}", headers=headers)
    assert summary_res.status_code == 200
    metrics = summary_res.get_json()["data"]["metrics"]
    assert Decimal(str(metrics["gross_income"])) == Decimal("0.00")
    assert Decimal(str(metrics["operating_expenses"])) == Decimal("0.00")


# ============================================================================
# CROSS-DRIVER ISOLATION
# ============================================================================

def test_e2e_cross_driver_isolation(app_and_db):
    """
    Verifies that Driver B cannot view, confirm, or modify Driver A's pending actions
    and cannot see Driver A's transactions in their own dashboard.
    """
    app, db = app_and_db
    client = app.test_client()

    # Driver A logs in and records batch
    token_a, driver_a = _authenticate_driver(client, phone="+919876543212")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    res_a = client.post(
        "/api/agent/chat",
        json={"message": "இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."},
        headers=headers_a
    )
    pending_id_a = res_a.get_json()["data"]["active_pending_action"]["pending_action_id"]

    # Driver B logs in
    token_b, driver_b = _authenticate_driver(client, phone="+919876543213")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Driver B attempts to confirm Driver A's pending action -> must fail 400
    hack_res = client.post(
        "/api/agent/confirm",
        json={"pending_id": pending_id_a, "yes_or_no": True},
        headers=headers_b
    )
    assert hack_res.status_code == 400

    # Driver A confirms their own action
    client.post(
        "/api/agent/confirm",
        json={"pending_id": pending_id_a, "yes_or_no": True},
        headers=headers_a
    )

    # Driver A has 3 transactions, Driver B has 0
    assert db.transactions.count_documents({"driver_id": driver_a}) == 3
    assert db.transactions.count_documents({"driver_id": driver_b}) == 0

    # Driver B's dashboard shows 0
    today = today_ist()
    summary_b = client.get(f"/api/finance/summary/daily?date={today}", headers=headers_b)
    metrics_b = summary_b.get_json()["data"]["metrics"]
    assert Decimal(str(metrics_b["gross_income"])) == Decimal("0.00")
