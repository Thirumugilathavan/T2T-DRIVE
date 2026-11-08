"""
Unit tests for T2T DRIVE Multilingual NLU and Slot Extraction.
Verifies parsing of Tanglish, Tamil, and English driver phrases,
Tamil number word conversion, and intent classification.
"""

from decimal import Decimal
from app.agent.nlu import (
    MultilingualNLU,
    AgentIntent,
    parse_numeric_amount,
    detect_language
)


def test_detect_language():
    assert detect_language("டீசல் 400 போட்டேன்") == "tamil"
    assert detect_language("savari 1200 aachu anna") == "tanglish"
    assert detect_language("diesel 400 potten") == "tanglish"
    assert detect_language("recorded fuel 500") == "english"


def test_parse_numeric_amount_digits():
    assert parse_numeric_amount("diesel 400 potten") == Decimal("400")
    assert parse_numeric_amount("savari ₹1200 aachu") == Decimal("1200")
    assert parse_numeric_amount("tea 20.50 rs") == Decimal("20.50")
    assert parse_numeric_amount("ownerukku 350 rubai kuduthen") == Decimal("350")
    assert parse_numeric_amount("toll 60") == Decimal("60")


def test_parse_numeric_amount_tamil_words():
    assert parse_numeric_amount("diesel ainooru potten") == Decimal("500")
    assert parse_numeric_amount("savari aayiram aachu") == Decimal("1000")
    assert parse_numeric_amount("tea iruvadhu ruba") == Decimal("20")
    assert parse_numeric_amount("petrol naanooru") == Decimal("400")
    assert parse_numeric_amount("ownerukku munnooru kuduthen") == Decimal("300")


def test_tanglish_expense_intents():
    p1 = MultilingualNLU.parse("diesel 450 potten")
    assert p1["intent"] == AgentIntent.RECORD_EXPENSE
    assert p1["slots"]["category"] == "FUEL"
    assert p1["slots"]["amount"] == 450.0
    assert len(p1["missing_slots"]) == 0

    p2 = MultilingualNLU.parse("tea tiffin 70 rs aachu")
    assert p2["intent"] == AgentIntent.RECORD_EXPENSE
    assert p2["slots"]["category"] == "FOOD"
    assert p2["slots"]["amount"] == 70.0

    p3 = MultilingualNLU.parse("puncture 100 potten")
    assert p3["intent"] == AgentIntent.RECORD_EXPENSE
    assert p3["slots"]["category"] == "MAINTENANCE"
    assert p3["slots"]["amount"] == 100.0


def test_tamil_script_expense_and_income():
    p1 = MultilingualNLU.parse("டீசல் 400 போட்டேன்")
    assert p1["intent"] == AgentIntent.RECORD_EXPENSE
    assert p1["slots"]["category"] == "FUEL"
    assert p1["slots"]["amount"] == 400.0
    assert p1["language"] == "tamil"

    p2 = MultilingualNLU.parse("சவாரி 1500 வந்தது")
    assert p2["intent"] == AgentIntent.RECORD_INCOME
    assert p2["slots"]["category"] == "FARE"
    assert p2["slots"]["amount"] == 1500.0
    assert p2["language"] == "tamil"


def test_income_and_owner_payment_intents():
    p_inc = MultilingualNLU.parse("savari 1200 aachu")
    assert p_inc["intent"] == AgentIntent.RECORD_INCOME
    assert p_inc["slots"]["category"] == "FARE"
    assert p_inc["slots"]["amount"] == 1200.0

    p_own = MultilingualNLU.parse("ownerukku 350 kuduthen")
    assert p_own["intent"] == AgentIntent.RECORD_OWNER_PAYMENT
    assert p_own["slots"]["category"] == "OWNER_RENT"
    assert p_own["slots"]["amount"] == 350.0


def test_missing_slot_detection():
    # Driver mentioned diesel without specifying amount
    p = MultilingualNLU.parse("diesel potten anna")
    assert p["intent"] == AgentIntent.RECORD_EXPENSE
    assert p["slots"]["category"] == "FUEL"
    assert p["slots"]["amount"] is None
    assert "amount" in p["missing_slots"]


def test_confirmation_and_cancellation_detection():
    # When active pending action is False, 'confirm' is just unknown or help
    p_idle = MultilingualNLU.parse("confirm", has_active_pending_action=False)
    assert p_idle["intent"] != AgentIntent.CONFIRM_ACTION

    # When active pending action is True:
    for term in ["yes", "confirm", "ok", "aama", "sari", "pannu", "ஆம்", "உறுதி"]:
        res = MultilingualNLU.parse(term, has_active_pending_action=True)
        assert res["intent"] == AgentIntent.CONFIRM_ACTION

    for term in ["no", "cancel", "vendaam", "illa", "thappu", "வேண்டாம்", "ரத்து"]:
        res = MultilingualNLU.parse(term, has_active_pending_action=True)
        assert res["intent"] == AgentIntent.CANCEL_ACTION


def test_summary_and_settlement_intents():
    p_sum1 = MultilingualNLU.parse("inniku kanaku sollu")
    assert p_sum1["intent"] == AgentIntent.GET_SUMMARY

    p_sum2 = MultilingualNLU.parse("today summary")
    assert p_sum2["intent"] == AgentIntent.GET_SUMMARY

    p_settle = MultilingualNLU.parse("settlement panni kudu")
    assert p_settle["intent"] == AgentIntent.CALCULATE_SETTLEMENT


def test_vehicle_extraction_from_speech():
    p = MultilingualNLU.parse("diesel 500 for TN-09-CD-5678")
    assert p["slots"]["vehicle_id"] == "TN-09-CD-5678"
    assert p["slots"]["amount"] == 500.0
