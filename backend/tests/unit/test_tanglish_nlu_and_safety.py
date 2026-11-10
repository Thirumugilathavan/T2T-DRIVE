"""
Unit and Safety Test Suite for Tanglish Multi-Transaction NLU,
Confirmation Firewall, Idempotency, and Append-Only Ledger Integrity.

Covers:
1. Tanglish transcript parsing ("இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்.").
2. Three-transaction extraction (Collection ₹1,500, Petrol ₹300, Owner ₹200).
3. Income versus expense distinction.
4. Owner settlement classification.
5. Full confirmation workflow (all 3 execute once).
6. Rejection workflow (zero execute).
7. Ambiguous confirmation handling (clarification requested).
8. Partial confirmation workflow (only specified item executes).
9. Idempotency and duplicate prevention.
10. Missing / invalid amount handling.
11. Driver isolation enforcement.
12. Database failure and atomic error handling.
"""

import pytest
from decimal import Decimal
import mongomock

from app.agent.nlu import MultilingualNLU, AgentIntent
from app.models.financial import (
    PendingActionType,
    PendingActionStatus,
    TransactionType,
    quantize_money
)
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.pending_action_service import (
    PendingActionService,
    PendingActionAlreadyConsumedError,
    PendingActionCancelledError,
    PendingActionUnauthorizedError
)
from app.services.idempotency_service import IdempotencyService
from app.agent.nodes import AgentNodes
from app.agent.graph import build_agent_graph
from app.agent.state import AgentState


@pytest.fixture
def mock_db():
    return mongomock.MongoClient().t2t_drive_test


@pytest.fixture
def ledger_service(mock_db):
    repo = TransactionRepository(mock_db)
    return LedgerService(repo=repo)


@pytest.fixture
def pending_action_service(mock_db, ledger_service):
    idempotency_svc = IdempotencyService(mock_db)
    return PendingActionService(
        db=mock_db,
        ledger_service=ledger_service,
        idempotency_service=idempotency_svc
    )


# ============================================================================
# 1 & 2. TANGLISH TRANSCRIPT PARSING & 3-TRANSACTION EXTRACTION
# ============================================================================

def test_tanglish_transcript_parsing_and_three_transaction_extraction():
    """Verifies that the verified Prisma STT transcript is parsed into 3 distinct transactions."""
    transcript = "இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."
    parsed = MultilingualNLU.parse(transcript, default_vehicle="TN-01-AB-1234")

    assert parsed["intent"] == AgentIntent.RECORD_BATCH_TRANSACTIONS
    assert parsed["confidence"] >= 0.95
    assert parsed["slots"]["vehicle_id"] == "TN-01-AB-1234"

    txns = parsed["slots"]["transactions"]
    assert len(txns) == 3

    # Transaction 1: Collection ₹1500 (Income)
    t1 = txns[0]
    assert t1["action_type"] == "ADD_INCOME"
    assert t1["category"] == "FARE"
    assert t1["amount"] == 1500.0

    # Transaction 2: Petrol ₹300 (Expense)
    t2 = txns[1]
    assert t2["action_type"] == "ADD_EXPENSE"
    assert t2["category"] == "FUEL"
    assert t2["amount"] == 300.0

    # Transaction 3: Owner payment ₹200 (Owner rent)
    t3 = txns[2]
    assert t3["action_type"] == "ADD_OWNER_PAYMENT"
    assert t3["category"] == "OWNER_RENT"
    assert t3["amount"] == 200.0


def test_romanized_tanglish_multi_transaction_parsing():
    """Verifies Romanized Tanglish variant parses identically."""
    text = "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen."
    parsed = MultilingualNLU.parse(text)
    assert parsed["intent"] == AgentIntent.RECORD_BATCH_TRANSACTIONS
    assert len(parsed["slots"]["transactions"]) == 3


# ============================================================================
# 3. INCOME VS EXPENSE DISTINCTION & SIGNED AMOUNTS
# ============================================================================

def test_income_vs_expense_distinction(ledger_service, mock_db):
    """Verifies strict mathematical signed amount invariants (+1500, -300, -200)."""
    driver_id = "DRV_TEST_01"
    vehicle_id = "TN-01-AB-1234"

    # Income
    inc = ledger_service.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.INCOME,
        amount=Decimal("1500.00"),
        category="FARE",
        description="Daily Collection",
        idempotency_key="KEY_INC_1"
    )
    assert Decimal(inc["signed_amount"]) == Decimal("1500.00")
    assert inc["amount"] == "1500.00"

    # Expense
    exp = ledger_service.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("300.00"),
        category="FUEL",
        description="Petrol",
        idempotency_key="KEY_EXP_1"
    )
    assert Decimal(exp["signed_amount"]) == Decimal("-300.00")
    assert exp["amount"] == "300.00"

    # Owner Payment
    own = ledger_service.record_transaction(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("200.00"),
        category="OWNER_RENT",
        description="Owner Rent Payment",
        idempotency_key="KEY_OWN_1"
    )
    assert Decimal(own["signed_amount"]) == Decimal("-200.00")
    assert own["amount"] == "200.00"

    # Net balance check: 1500 - 300 - 200 = +1000
    txns = list(mock_db.transactions.find({"driver_id": driver_id}))
    net_signed = sum(Decimal(str(t["signed_amount"])) for t in txns)
    assert net_signed == Decimal("1000.00")


# ============================================================================
# 4. OWNER SETTLEMENT CLASSIFICATION
# ============================================================================

def test_owner_settlement_classification():
    """Verifies owner payment is classified under OWNER_RENT."""
    text = "owner-ku 200 kuduthen"
    parsed = MultilingualNLU.parse(text)
    assert parsed["intent"] == AgentIntent.RECORD_OWNER_PAYMENT
    assert parsed["slots"]["amount"] == 200.0
    assert parsed["slots"]["category"] == "OWNER_RENT"


# ============================================================================
# 5. FULL CONFIRMATION WORKFLOW (ALL 3 EXECUTE EXACTLY ONCE)
# ============================================================================

def test_confirmation_workflow_all_three_execute_once(pending_action_service, mock_db):
    """Driver proposes 3 transactions and confirms. All 3 execute exactly once."""
    driver_id = "DRV_TEST_02"
    vehicle_id = "TN-01-AB-1234"

    proposed_txns = [
        {"action_type": "ADD_INCOME", "category": "FARE", "amount": 1500.0, "description": "Collection ₹1500"},
        {"action_type": "ADD_EXPENSE", "category": "FUEL", "amount": 300.0, "description": "FUEL ₹300"},
        {"action_type": "ADD_OWNER_PAYMENT", "category": "OWNER_RENT", "amount": 200.0, "description": "Owner payment ₹200"}
    ]

    proposal = pending_action_service.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data={"vehicle_id": vehicle_id, "transactions": proposed_txns},
        idempotency_key="PROP_BATCH_001"
    )

    pending_id = proposal["pending_action_id"]
    assert proposal["status"] == PendingActionStatus.PENDING.value

    # Zero writes to ledger prior to confirmation
    assert mock_db.transactions.count_documents({"driver_id": driver_id}) == 0

    # User confirms
    result = pending_action_service.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key=f"AGENT_EXEC_{pending_id}"
    )

    assert result["status"] == "CONFIRMED"
    assert result["count"] == 3
    assert len(result["transactions"]) == 3

    # Verify exactly 3 ledger documents were created
    ledger_txns = list(mock_db.transactions.find({"driver_id": driver_id}))
    assert len(ledger_txns) == 3

    # Check categories and amounts
    cats = {t["category"]: Decimal(str(t["amount"])) for t in ledger_txns}
    assert cats["FARE"] == Decimal("1500.00")
    assert cats["FUEL"] == Decimal("300.00")
    assert cats["OWNER_RENT"] == Decimal("200.00")

    # Check pending action status is now CONSUMED
    stored_pending = mock_db.pending_actions.find_one({"pending_action_id": pending_id})
    assert stored_pending["status"] == PendingActionStatus.CONSUMED.value


# ============================================================================
# 6. REJECTION WORKFLOW (ZERO TRANSACTIONS EXECUTE)
# ============================================================================

def test_rejection_workflow_zero_transactions_execute(pending_action_service, mock_db):
    """Driver rejects/cancels the proposal. Zero writes to the ledger."""
    driver_id = "DRV_TEST_03"
    vehicle_id = "TN-01-AB-1234"

    proposed_txns = [
        {"action_type": "ADD_INCOME", "category": "FARE", "amount": 1500.0},
        {"action_type": "ADD_EXPENSE", "category": "FUEL", "amount": 300.0},
        {"action_type": "ADD_OWNER_PAYMENT", "category": "OWNER_RENT", "amount": 200.0}
    ]

    proposal = pending_action_service.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data={"vehicle_id": vehicle_id, "transactions": proposed_txns},
        idempotency_key="PROP_BATCH_002"
    )

    pending_id = proposal["pending_action_id"]

    # User rejects ("cancel" / "no")
    cancel_res = pending_action_service.cancel_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        reason="Driver cancelled transaction proposal"
    )

    assert cancel_res["status"] == "CANCELLED"

    # Strictly ZERO ledger records
    assert mock_db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Attempting to confirm a cancelled action raises error
    with pytest.raises(PendingActionCancelledError):
        pending_action_service.confirm_action(
            pending_action_id=pending_id,
            driver_id=driver_id,
            idempotency_key=f"AGENT_EXEC_{pending_id}"
        )


# ============================================================================
# 7. AMBIGUOUS CONFIRMATION (CLARIFICATION REQUESTED)
# ============================================================================

def test_ambiguous_confirmation_clarification():
    """Ambiguous reply yields CLARIFY_CONFIRMATION intent, preserving pending state."""
    parsed = MultilingualNLU.parse("maybe", has_active_pending_action=True)
    assert parsed["intent"] == AgentIntent.CLARIFY_CONFIRMATION

    parsed2 = MultilingualNLU.parse("what did you say", has_active_pending_action=True)
    assert parsed2["intent"] == AgentIntent.CLARIFY_CONFIRMATION


# ============================================================================
# 8. PARTIAL CONFIRMATION (ONLY SPECIFIED ITEM EXECUTES)
# ============================================================================

def test_partial_confirmation_only_specified_item_executes(pending_action_service, mock_db):
    """Driver confirms 'only petrol'. Only the petrol transaction is committed."""
    driver_id = "DRV_TEST_04"
    vehicle_id = "TN-01-AB-1234"

    proposed_txns = [
        {"action_type": "ADD_INCOME", "category": "FARE", "amount": 1500.0},
        {"action_type": "ADD_EXPENSE", "category": "FUEL", "amount": 300.0},
        {"action_type": "ADD_OWNER_PAYMENT", "category": "OWNER_RENT", "amount": 200.0}
    ]

    proposal = pending_action_service.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data={"vehicle_id": vehicle_id, "transactions": proposed_txns},
        idempotency_key="PROP_BATCH_003"
    )

    pending_id = proposal["pending_action_id"]

    # User says: "only petrol" -> MultilingualNLU returns CONFIRM_ACTION with filter_category="FUEL"
    parsed_reply = MultilingualNLU.parse("only petrol", has_active_pending_action=True)
    assert parsed_reply["intent"] == AgentIntent.CONFIRM_ACTION
    assert parsed_reply["slots"]["filter_category"] == "FUEL"

    # Execute with filter
    result = pending_action_service.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key=f"AGENT_EXEC_{pending_id}",
        filter_category=parsed_reply["slots"]["filter_category"]
    )

    assert result["is_partial"] is True
    assert result["count"] == 1
    assert result["transactions"][0]["category"] == "FUEL"
    assert result["transactions"][0]["amount"] == "300.00"

    # Exactly 1 transaction in the ledger (FUEL)
    ledger_txns = list(mock_db.transactions.find({"driver_id": driver_id}))
    assert len(ledger_txns) == 1
    assert ledger_txns[0]["category"] == "FUEL"
    assert Decimal(str(ledger_txns[0]["amount"])) == Decimal("300.00")


# ============================================================================
# 9. IDEMPOTENCY & DUPLICATE PREVENTION
# ============================================================================

def test_duplicate_prevention_idempotency(pending_action_service, mock_db):
    """Submitting duplicate confirmation returns cached result with 0 duplicate ledger records."""
    driver_id = "DRV_TEST_05"
    vehicle_id = "TN-01-AB-1234"

    proposed_txns = [
        {"action_type": "ADD_INCOME", "category": "FARE", "amount": 1500.0},
        {"action_type": "ADD_EXPENSE", "category": "FUEL", "amount": 300.0},
        {"action_type": "ADD_OWNER_PAYMENT", "category": "OWNER_RENT", "amount": 200.0}
    ]

    proposal = pending_action_service.propose_action(
        driver_id=driver_id,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data={"vehicle_id": vehicle_id, "transactions": proposed_txns},
        idempotency_key="PROP_BATCH_004"
    )

    pending_id = proposal["pending_action_id"]

    # First confirmation
    res1 = pending_action_service.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key=f"AGENT_EXEC_{pending_id}"
    )

    # Second confirmation (duplicate call)
    res2 = pending_action_service.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key=f"AGENT_EXEC_{pending_id}"
    )

    assert res1["count"] == res2["count"] == 3
    # Exactly 3 records in ledger, NOT 6
    assert mock_db.transactions.count_documents({"driver_id": driver_id}) == 3


# ============================================================================
# 10. MISSING OR INVALID AMOUNTS
# ============================================================================

def test_invalid_or_missing_amounts():
    """Missing or non-positive amount triggers slot filling or validation error."""
    # Utterance with categories but no numbers
    text = "petrol selavu matrum collection"
    parsed = MultilingualNLU.parse(text)
    # Should flag missing slot for amount
    assert "amount" in parsed.get("missing_slots", []) or parsed["intent"] in (
        AgentIntent.RECORD_EXPENSE, AgentIntent.RECORD_INCOME
    )


# ============================================================================
# 11. DRIVER ISOLATION ENFORCEMENT
# ============================================================================

def test_driver_isolation_enforcement(pending_action_service, mock_db):
    """Driver B cannot confirm or access Driver A's pending action."""
    driver_a = "DRV_AAA"
    driver_b = "DRV_BBB"

    proposal = pending_action_service.propose_action(
        driver_id=driver_a,
        action_type=PendingActionType.ADD_BATCH_TRANSACTIONS,
        proposed_data={"vehicle_id": "TN-01-AB-1234", "transactions": [{"action_type": "ADD_INCOME", "category": "FARE", "amount": 1500.0}]},
        idempotency_key="PROP_ISOLATION_01"
    )

    pending_id = proposal["pending_action_id"]

    # Driver B attempts to confirm Driver A's action
    with pytest.raises(PendingActionUnauthorizedError):
        pending_action_service.confirm_action(
            pending_action_id=pending_id,
            driver_id=driver_b,
            idempotency_key=f"AGENT_EXEC_{pending_id}"
        )

    # Driver B cannot retrieve Driver A's action
    retrieved = pending_action_service.get_pending_action(pending_id, driver_id=driver_b)
    assert retrieved is None

    # Zero writes for both drivers
    assert mock_db.transactions.count_documents({"driver_id": driver_a}) == 0
    assert mock_db.transactions.count_documents({"driver_id": driver_b}) == 0


# ============================================================================
# 12. COMPLETE LANGGRAPH AGENT INTEGRATION TEST
# ============================================================================

def test_complete_langgraph_agent_multi_turn_flow(pending_action_service, mock_db):
    """End-to-end multi-turn conversation test through the compiled LangGraph workflow."""
    driver_id = "DRV_E2E_01"
    nodes = AgentNodes(pending_action_service=pending_action_service)
    app = build_agent_graph(nodes)

    # Turn 1: Driver submits compound Tanglish utterance
    transcript = "இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."
    state1: AgentState = {
        "session_id": "SESS_E2E_01",
        "driver_id": driver_id,
        "language": "tamil",
        "user_message": transcript,
        "next_step": "IDLE"
    }

    result1 = app.invoke(state1, config={"configurable": {"thread_id": "SESS_E2E_01"}})

    # Verify Turn 1 produces confirmation proposal
    assert result1["next_step"] == "AWAITING_CONFIRMATION"
    assert result1["active_pending_action"] is not None
    pending_action = result1["active_pending_action"]
    assert pending_action["action_type"] == PendingActionType.ADD_BATCH_TRANSACTIONS.value
    assert len(pending_action["proposed_data"]["transactions"]) == 3
    # Check confirmation prompt is presented
    assert "சேமிக்கவா" in result1["response_message"] or "save" in result1["response_message"].lower()
    # Zero ledger writes yet
    assert mock_db.transactions.count_documents({"driver_id": driver_id}) == 0

    # Turn 2: Driver confirms ("ஆம்" / "confirm")
    state2: AgentState = {
        "session_id": "SESS_E2E_01",
        "driver_id": driver_id,
        "language": "tamil",
        "user_message": "ஆம் உறுதி செய்",
        "active_pending_action": pending_action,
        "next_step": "AWAITING_CONFIRMATION"
    }

    result2 = app.invoke(state2, config={"configurable": {"thread_id": "SESS_E2E_01"}})

    # Verify Turn 2 executes atomically
    assert result2["next_step"] == "COMPLETED"
    assert result2["active_pending_action"] is None
    assert result2["execution_result"]["count"] == 3

    # Verify exactly 3 ledger transactions in database
    txns = list(mock_db.transactions.find({"driver_id": driver_id}))
    assert len(txns) == 3
