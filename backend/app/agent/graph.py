"""
LangGraph State Machine Definition for T2T DRIVE Conversational Agent.
Assembles the state graph, defines nodes, sets routing logic, and compiles with checkpointer.
Includes Phase 5 support for Document, Challan, and Maintenance assistance.
"""

from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.state import AgentState
from app.agent.nodes import AgentNodes
from app.agent.nlu import AgentIntent


def route_after_nlu(state: AgentState) -> str:
    """
    Determines next state node based on intent, slots, and active pending action.
    """
    has_pending = bool(state.get("active_pending_action"))
    intent = state.get("intent", AgentIntent.UNKNOWN)
    missing = state.get("missing_slots", [])

    # 1. Active pending action confirmation or cancellation has top priority
    if has_pending and intent == AgentIntent.CONFIRM_ACTION:
        return "execute_action"
    if has_pending and intent == AgentIntent.CANCEL_ACTION:
        return "cancel_action"

    # 2. If missing required slots (e.g. amount was not provided for an expense)
    if missing:
        return "slot_filling"

    # 3. Financial transaction proposals
    if intent in (
        AgentIntent.RECORD_EXPENSE,
        AgentIntent.RECORD_INCOME,
        AgentIntent.RECORD_OWNER_PAYMENT,
        AgentIntent.ADD_MAINTENANCE
    ):
        return "propose_action"

    # 4. Phase 5 Document Assistance Intents
    if intent == AgentIntent.CHECK_DOCUMENT_EXPIRY:
        return "query_document_expiry"
    if intent == AgentIntent.LIST_DOCUMENTS:
        return "query_documents_list"

    # 5. Phase 5 Challan Assistance Intents
    if intent in (AgentIntent.CHECK_UNPAID_CHALLANS, AgentIntent.LIST_CHALLANS):
        return "query_unpaid_challans"

    # 6. Phase 5 Maintenance Schedule Intents
    if intent in (AgentIntent.CHECK_UPCOMING_SERVICE, AgentIntent.CHECK_OVERDUE_SERVICE):
        return "query_upcoming_service"

    # 7. Passenger Extension Trip Intents
    if intent == AgentIntent.START_TRIP:
        return "start_trip"
    if intent == AgentIntent.CHANGE_DESTINATION:
        return "trip_destination"
    if intent == AgentIntent.ADD_STOP:
        return "trip_stop"
    if intent == AgentIntent.CHANGE_FARE:
        return "trip_fare"
    if intent == AgentIntent.RECORD_TRIP_PAYMENT:
        return "trip_payment"

    # 8. Reporting intents
    if intent == AgentIntent.GET_SUMMARY:
        return "query_summary"
    if intent == AgentIntent.CALCULATE_SETTLEMENT:
        return "query_settlement"

    # 9. Help guidance
    if intent == AgentIntent.HELP:
        return "help"

    # 10. Fallback
    return "fallback"


def build_agent_graph(nodes: AgentNodes, checkpointer=None):
    """
    Builds and compiles the conversational state graph.
    """
    workflow = StateGraph(AgentState)

    # Register Nodes
    workflow.add_node("nlu", nodes.nlu_node)
    workflow.add_node("slot_filling", nodes.slot_filling_node)
    workflow.add_node("propose_action", nodes.action_proposal_node)
    workflow.add_node("execute_action", nodes.action_execution_node)
    workflow.add_node("cancel_action", nodes.action_cancellation_node)
    workflow.add_node("query_summary", nodes.query_summary_node)
    workflow.add_node("query_settlement", nodes.query_settlement_node)
    workflow.add_node("query_document_expiry", nodes.query_document_expiry_node)
    workflow.add_node("query_documents_list", nodes.query_documents_list_node)
    workflow.add_node("query_unpaid_challans", nodes.query_unpaid_challans_node)
    workflow.add_node("query_upcoming_service", nodes.query_upcoming_service_node)
    workflow.add_node("start_trip", nodes.start_trip_node)
    workflow.add_node("trip_destination", nodes.trip_destination_node)
    workflow.add_node("trip_stop", nodes.trip_stop_node)
    workflow.add_node("trip_fare", nodes.trip_fare_node)
    workflow.add_node("trip_payment", nodes.trip_payment_node)
    workflow.add_node("help", nodes.help_node)
    workflow.add_node("fallback", nodes.fallback_node)

    # Entry edge
    workflow.add_edge(START, "nlu")

    # Conditional routing after NLU
    workflow.add_conditional_edges(
        "nlu",
        route_after_nlu,
        {
            "execute_action": "execute_action",
            "cancel_action": "cancel_action",
            "slot_filling": "slot_filling",
            "propose_action": "propose_action",
            "query_summary": "query_summary",
            "query_settlement": "query_settlement",
            "query_document_expiry": "query_document_expiry",
            "query_documents_list": "query_documents_list",
            "query_unpaid_challans": "query_unpaid_challans",
            "query_upcoming_service": "query_upcoming_service",
            "start_trip": "start_trip",
            "trip_destination": "trip_destination",
            "trip_stop": "trip_stop",
            "trip_fare": "trip_fare",
            "trip_payment": "trip_payment",
            "help": "help",
            "fallback": "fallback",
        }
    )

    # Terminal transitions
    workflow.add_edge("slot_filling", END)
    workflow.add_edge("propose_action", END)
    workflow.add_edge("execute_action", END)
    workflow.add_edge("cancel_action", END)
    workflow.add_edge("query_summary", END)
    workflow.add_edge("query_settlement", END)
    workflow.add_edge("query_document_expiry", END)
    workflow.add_edge("query_documents_list", END)
    workflow.add_edge("query_unpaid_challans", END)
    workflow.add_edge("query_upcoming_service", END)
    workflow.add_edge("start_trip", END)
    workflow.add_edge("trip_destination", END)
    workflow.add_edge("trip_stop", END)
    workflow.add_edge("trip_fare", END)
    workflow.add_edge("trip_payment", END)
    workflow.add_edge("help", END)
    workflow.add_edge("fallback", END)

    # Compile with memory checkpointer
    cp = checkpointer if checkpointer is not None else MemorySaver()
    compiled_app = workflow.compile(checkpointer=cp)
    return compiled_app
