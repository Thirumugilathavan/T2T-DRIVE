"""
LangGraph State Machine Definition for T2T DRIVE Conversational Agent.
Assembles the state graph, defines nodes, sets routing logic, and compiles with checkpointer.
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

    # 2. If missing required slots (e.g. amount was not provided)
    if missing:
        return "slot_filling"

    # 3. Financial transaction proposals
    if intent in (
        AgentIntent.RECORD_EXPENSE,
        AgentIntent.RECORD_INCOME,
        AgentIntent.RECORD_OWNER_PAYMENT
    ):
        return "propose_action"

    # 4. Reporting intents
    if intent == AgentIntent.GET_SUMMARY:
        return "query_summary"
    if intent == AgentIntent.CALCULATE_SETTLEMENT:
        return "query_settlement"

    # 5. Help guidance
    if intent == AgentIntent.HELP:
        return "help"

    # 6. Fallback
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
    workflow.add_edge("help", END)
    workflow.add_edge("fallback", END)

    # Compile with memory checkpointer
    cp = checkpointer if checkpointer is not None else MemorySaver()
    compiled_app = workflow.compile(checkpointer=cp)
    return compiled_app
