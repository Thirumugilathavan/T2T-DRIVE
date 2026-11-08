"""
Unit Tests for Phase 5 Multilingual NLU Parsing.
Verifies Tamil, Tanglish, and English intent and entity extraction for
documents, challans, and vehicle maintenance.
"""

from decimal import Decimal
from app.agent.nlu import MultilingualNLU, AgentIntent


def test_document_expiry_queries():
    # Tanglish
    res_tg = MultilingualNLU.parse("En insurance eppo expire aagum?")
    assert res_tg["intent"] == AgentIntent.CHECK_DOCUMENT_EXPIRY
    assert res_tg["slots"]["document_type"] == "INSURANCE"

    # Tamil script
    res_ta = MultilingualNLU.parse("என் இன்சூரன்ஸ் எப்போ முடியும்?")
    assert res_ta["intent"] == AgentIntent.CHECK_DOCUMENT_EXPIRY
    assert res_ta["slots"]["document_type"] == "INSURANCE"

    # English
    res_en = MultilingualNLU.parse("When does my insurance expire?")
    assert res_en["intent"] == AgentIntent.CHECK_DOCUMENT_EXPIRY
    assert res_en["slots"]["document_type"] == "INSURANCE"

    # PUC check
    res_puc = MultilingualNLU.parse("When does my PUC expire?")
    assert res_puc["intent"] == AgentIntent.CHECK_DOCUMENT_EXPIRY
    assert res_puc["slots"]["document_type"] == "PUC"


def test_documents_list_queries():
    res_en = MultilingualNLU.parse("Show my vehicle documents.")
    assert res_en["intent"] == AgentIntent.LIST_DOCUMENTS

    res_tg = MultilingualNLU.parse("Enna documents irukku?")
    assert res_tg["intent"] == AgentIntent.LIST_DOCUMENTS


def test_unpaid_challan_queries():
    # Tanglish
    res_tg = MultilingualNLU.parse("Enakku unpaid challan irukka?")
    assert res_tg["intent"] == AgentIntent.CHECK_UNPAID_CHALLANS

    # English
    res_en = MultilingualNLU.parse("Show my unpaid challans.")
    assert res_en["intent"] == AgentIntent.CHECK_UNPAID_CHALLANS

    # Tamil script
    res_ta = MultilingualNLU.parse("எனக்கு டிராஃபிக் ஃபைன் அல்லது சலான் இருக்கா?")
    assert res_ta["intent"] == AgentIntent.CHECK_UNPAID_CHALLANS


def test_upcoming_service_queries():
    # Tanglish
    res_tg = MultilingualNLU.parse("En auto ku service eppo?")
    assert res_tg["intent"] == AgentIntent.CHECK_UPCOMING_SERVICE

    # English
    res_en = MultilingualNLU.parse("When is my next service due?")
    assert res_en["intent"] == AgentIntent.CHECK_UPCOMING_SERVICE

    # Tamil script
    res_ta = MultilingualNLU.parse("என் வண்டிக்கு சர்வீஸ் எப்போது?")
    assert res_ta["intent"] == AgentIntent.CHECK_UPCOMING_SERVICE


def test_maintenance_expense_utterances():
    # Tanglish
    res_tg = MultilingualNLU.parse("Auto service ku 1200 rooba selavu aachu.")
    assert res_tg["intent"] in (AgentIntent.RECORD_EXPENSE, AgentIntent.ADD_MAINTENANCE)
    assert res_tg["slots"]["category"] == "MAINTENANCE"
    assert res_tg["slots"]["amount"] == 1200.0

    # Tamil script
    res_ta = MultilingualNLU.parse("இன்று 1200 ரூபாய் சர்வீஸ்க்கு செலவு செய்தேன்.")
    assert res_ta["intent"] in (AgentIntent.RECORD_EXPENSE, AgentIntent.ADD_MAINTENANCE)
    assert res_ta["slots"]["category"] == "MAINTENANCE"
    assert res_ta["slots"]["amount"] == 1200.0

    # English
    res_en = MultilingualNLU.parse("I spent 1200 rupees on vehicle maintenance.")
    assert res_en["intent"] in (AgentIntent.RECORD_EXPENSE, AgentIntent.ADD_MAINTENANCE)
    assert res_en["slots"]["category"] == "MAINTENANCE"
    assert res_en["slots"]["amount"] == 1200.0


def test_maintenance_missing_amount_triggers_slot_filling():
    res = MultilingualNLU.parse("Auto service panninen.")
    assert "amount" in res["missing_slots"]
    assert res["slots"]["category"] == "MAINTENANCE"
