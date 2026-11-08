"""
Unit tests for LangGraph State Machine and Node Transitions in T2T DRIVE.
Validates state propagation, proposal creation, execution, and cancellation flows.
"""

import mongomock
from unittest.mock import MagicMock
from decimal import Decimal

from app.agent.state import AgentState
from app.agent.nodes import AgentNodes
from app.agent.graph import build_agent_graph, route_after_nlu
from app.agent.nlu import AgentIntent
from app.models.financial import PendingActionType, TransactionType


def test_route_after_nlu_logic():
    # 1. Active pending action with confirm intent
    s1: AgentState = {
        "active_pending_action": {"pending_action_id": "PEND_123"},
        "intent": AgentIntent.CONFIRM_ACTION,
        "missing_slots": []
    }
    assert route_after_nlu(s1) == "execute_action"

    # 2. Active pending action with cancel intent
    s2: AgentState = {
        "active_pending_action": {"pending_action_id": "PEND_123"},
        "intent": AgentIntent.CANCEL_ACTION,
        "missing_slots": []
    }
    assert route_after_nlu(s2) == "cancel_action"

    # 3. Missing slots triggers slot_filling
    s3: AgentState = {
        "intent": AgentIntent.RECORD_EXPENSE,
        "missing_slots": ["amount"]
    }
    assert route_after_nlu(s3) == "slot_filling"

    # 4. Financial intent without missing slots routes to propose_action
    s4: AgentState = {
        "intent": AgentIntent.RECORD_EXPENSE,
        "missing_slots": []
    }
    assert route_after_nlu(s4) == "propose_action"

    # 5. Summary and settlement
    s5: AgentState = {"intent": AgentIntent.GET_SUMMARY, "missing_slots": []}
    assert route_after_nlu(s5) == "query_summary"

    s6: AgentState = {"intent": AgentIntent.CALCULATE_SETTLEMENT, "missing_slots": []}
    assert route_after_nlu(s6) == "query_settlement"


def test_agent_nodes_proposal_and_firewall():
    mock_pending_svc = MagicMock()
    mock_pending_svc.propose_action.return_value = {
        "pending_action_id": "PEND_TEST_999",
        "status": "PENDING",
        "action_type": "ADD_EXPENSE",
        "proposed_data": {"amount": "400.00", "category": "FUEL", "vehicle_id": "TN-01-AB-1234"}
    }

    nodes = AgentNodes(pending_action_service=mock_pending_svc)

    state: AgentState = {
        "driver_id": "DRV_123",
        "intent": AgentIntent.RECORD_EXPENSE,
        "language": "tanglish",
        "slots": {
            "amount": 400.0,
            "category": "FUEL",
            "vehicle_id": "TN-01-AB-1234"
        },
        "user_message": "diesel 400 potten"
    }

    result = nodes.action_proposal_node(state)

    # Verify pending action service was invoked with correct parameters
    mock_pending_svc.propose_action.assert_called_once()
    assert result["next_step"] == "AWAITING_CONFIRMATION"
    assert result["active_pending_action"]["pending_action_id"] == "PEND_TEST_999"
    assert "₹400.00" in result["response_message"]


def test_agent_nodes_execution():
    mock_pending_svc = MagicMock()
    mock_pending_svc.confirm_action.return_value = {
        "status": "CONFIRMED",
        "pending_action_id": "PEND_TEST_999",
        "execution_result": {"transaction_id": "TXN_777"}
    }

    nodes = AgentNodes(pending_action_service=mock_pending_svc)

    state: AgentState = {
        "driver_id": "DRV_123",
        "language": "tanglish",
        "active_pending_action": {
            "pending_action_id": "PEND_TEST_999",
            "action_type": "ADD_EXPENSE",
            "proposed_data": {"amount": "400.00", "category": "FUEL", "vehicle_id": "TN-01-AB-1234"}
        }
    }

    result = nodes.action_execution_node(state)

    # Verify confirm_action was called with deterministic key
    mock_pending_svc.confirm_action.assert_called_once_with(
        pending_action_id="PEND_TEST_999",
        driver_id="DRV_123",
        idempotency_key="AGENT_EXEC_PEND_TEST_999"
    )
    assert result["active_pending_action"] is None
    assert result["next_step"] == "COMPLETED"
    assert "vetrikaramaga" in result["response_message"].lower() or "done" in result["response_message"].lower()


def test_agent_nodes_cancellation():
    mock_pending_svc = MagicMock()
    nodes = AgentNodes(pending_action_service=mock_pending_svc)

    state: AgentState = {
        "driver_id": "DRV_123",
        "language": "tanglish",
        "active_pending_action": {
            "pending_action_id": "PEND_TEST_999"
        }
    }

    result = nodes.action_cancellation_node(state)

    mock_pending_svc.cancel_action.assert_called_once()
    assert result["active_pending_action"] is None
    assert result["next_step"] == "IDLE"
    assert "cancel" in result["response_message"].lower()


def test_agent_graph_full_invocation_cycle():
    mock_pending_svc = MagicMock()
    mock_pending_svc.propose_action.return_value = {
        "pending_action_id": "PEND_CYCLE_1",
        "status": "PENDING",
        "action_type": "ADD_EXPENSE",
        "proposed_data": {"amount": "500.00", "category": "FUEL", "vehicle_id": "TN-01-AB-1234"}
    }

    nodes = AgentNodes(pending_action_service=mock_pending_svc)
    graph = build_agent_graph(nodes)

    # Turn 1: Propose expense
    turn1_state = graph.invoke(
        {
            "driver_id": "DRV_ABC",
            "user_message": "diesel 500 potten",
            "language": "tanglish",
            "slots": {"vehicle_id": "TN-01-AB-1234"}
        },
        config={"configurable": {"thread_id": "test_thread_cycle"}}
    )

    assert turn1_state["next_step"] == "AWAITING_CONFIRMATION"
    assert turn1_state["active_pending_action"]["pending_action_id"] == "PEND_CYCLE_1"

    # Turn 2: Confirm
    mock_pending_svc.confirm_action.return_value = {
        "status": "CONFIRMED",
        "pending_action_id": "PEND_CYCLE_1"
    }

    turn2_state = graph.invoke(
        {
            "driver_id": "DRV_ABC",
            "user_message": "aama confirm pannu",
            "language": "tanglish",
            "active_pending_action": turn1_state["active_pending_action"],
            "slots": turn1_state["slots"]
        },
        config={"configurable": {"thread_id": "test_thread_cycle"}}
    )

    assert turn2_state["next_step"] == "COMPLETED"
    assert turn2_state["active_pending_action"] is None
