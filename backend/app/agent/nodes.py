"""
LangGraph Node Handlers for T2T DRIVE Conversational Agent.
Implements the core state transitions, pending action lifecycle, slot-filling,
and summary/settlement retrieval.
"""

import logging
import secrets
from decimal import Decimal
from typing import Dict, Any, Optional

from app.agent.state import AgentState
from app.agent.nlu import MultilingualNLU, AgentIntent
from app.agent.prompts import (
    prompt_proposal_confirmation,
    prompt_execution_success,
    prompt_cancellation_success,
    prompt_missing_slot,
    prompt_daily_summary,
    prompt_settlement_status,
    prompt_help,
    prompt_unknown
)
from app.models.financial import PendingActionType
from app.utils.dates import today_ist

logger = logging.getLogger("t2t_drive.agent_nodes")


class AgentNodes:
    """
    Encapsulates all LangGraph node functions with injected services.
    """

    def __init__(
        self,
        pending_action_service=None,
        summary_service=None,
        settlement_service=None,
        db=None
    ):
        self.pending_svc = pending_action_service
        self.summary_svc = summary_service
        self.settlement_svc = settlement_service
        self.db = db

    def nlu_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Parses user message into intent, language, and slots.
        Handles multi-turn slot merging when awaiting slot input.
        """
        message = state.get("user_message", "")
        has_pending = bool(state.get("active_pending_action"))
        default_vehicle = state.get("slots", {}).get("vehicle_id", "DEFAULT_VEHICLE")

        parsed = MultilingualNLU.parse(
            text=message,
            has_active_pending_action=has_pending,
            default_vehicle=default_vehicle
        )

        language = parsed["language"]
        intent = parsed["intent"]
        confidence = parsed["confidence"]
        new_slots = parsed.get("slots", {})
        missing_slots = parsed.get("missing_slots", [])

        # Check for multi-turn slot merging if the agent was previously awaiting a slot (e.g. amount)
        existing_slots = dict(state.get("slots", {}))
        if (state.get("next_step") == "AWAITING_SLOT" or intent == "PROVIDE_AMOUNT") and "amount" in new_slots and new_slots["amount"] is not None:
            # Driver just supplied the missing amount!
            existing_slots["amount"] = new_slots["amount"]
            if state.get("intent") and state.get("intent") != "PROVIDE_AMOUNT":
                intent = state["intent"]
            else:
                intent = AgentIntent.RECORD_EXPENSE
            missing_slots = [s for s in missing_slots if s != "amount"]
            merged_slots = existing_slots
        else:
            merged_slots = dict(existing_slots)
            for k, v in new_slots.items():
                if v is not None:
                    merged_slots[k] = v

        return {
            "intent": intent,
            "confidence": confidence,
            "language": language,
            "slots": merged_slots,
            "missing_slots": missing_slots
        }

    def slot_filling_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Prompts the driver for missing required parameters (e.g. amount).
        """
        language = state.get("language", "tanglish")
        category = state.get("slots", {}).get("category", "Expense")
        missing = state.get("missing_slots", ["amount"])

        prompt_data = prompt_missing_slot(slot_name=missing[0], category=category, language=language)

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "AWAITING_SLOT"
        }

    def action_proposal_node(self, state: AgentState) -> Dict[str, Any]:
        """
        FIREWALL ENFORCEMENT: Never write directly to the ledger!
        Creates a PENDING action via PendingActionService and asks the driver to confirm.
        """
        driver_id = state.get("driver_id", "")
        intent = state.get("intent", "")
        slots = state.get("slots", {})
        language = state.get("language", "tanglish")

        action_type_map = {
            AgentIntent.RECORD_EXPENSE: PendingActionType.ADD_EXPENSE,
            AgentIntent.RECORD_INCOME: PendingActionType.ADD_INCOME,
            AgentIntent.RECORD_OWNER_PAYMENT: PendingActionType.ADD_OWNER_PAYMENT,
        }
        action_type = action_type_map.get(intent)
        if not action_type:
            return {
                "error": f"Unknown financial intent: {intent}",
                "response_message": "Error creating financial proposal.",
                "response_voice_text": "Error creating financial proposal.",
                "next_step": "IDLE"
            }

        amount = slots.get("amount")
        category = slots.get("category", "OTHER_EXPENSE")
        vehicle_id = slots.get("vehicle_id", "DEFAULT_VEHICLE")

        proposed_data = {
            "vehicle_id": vehicle_id,
            "amount": str(amount),
            "category": category,
            "description": slots.get("notes", state.get("user_message", "")),
            "transaction_date": today_ist(),
            "source": "VOICE_AGENT"
        }

        # Generate unique idempotency key for proposal
        prop_idempotency_key = f"AGENT_PROP_{driver_id}_{secrets.token_hex(6)}"

        if self.pending_svc:
            try:
                pending_doc = self.pending_svc.propose_action(
                    driver_id=driver_id,
                    action_type=action_type,
                    proposed_data=proposed_data,
                    idempotency_key=prop_idempotency_key
                )
            except Exception as e:
                logger.error("Failed to propose pending action: %s", e)
                return {
                    "error": str(e),
                    "response_message": f"Could not create proposal: {str(e)}",
                    "response_voice_text": "Could not create proposal.",
                    "next_step": "IDLE"
                }
        else:
            # Fallback mock for testing without service
            pending_doc = {
                "pending_action_id": f"PEND_MOCK_{secrets.token_hex(6)}",
                "status": "PENDING",
                "proposed_data": proposed_data,
                "action_type": action_type.value
            }

        # Ensure pure JSON types for checkpointer serialization
        serializable_pending = dict(pending_doc)
        if "action_type" in serializable_pending and hasattr(serializable_pending["action_type"], "value"):
            serializable_pending["action_type"] = serializable_pending["action_type"].value
        if "status" in serializable_pending and hasattr(serializable_pending["status"], "value"):
            serializable_pending["status"] = serializable_pending["status"].value

        prompt_data = prompt_proposal_confirmation(
            action_type=action_type.value,
            amount=amount,
            category=category,
            vehicle_id=vehicle_id,
            language=language
        )

        return {
            "active_pending_action": serializable_pending,
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "AWAITING_CONFIRMATION"
        }

    def action_execution_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Executes the confirmed pending action atomically.
        Uses idempotency key EXEC_{pending_action_id}.
        """
        driver_id = state.get("driver_id", "")
        active_action = state.get("active_pending_action", {})
        pending_id = active_action.get("pending_action_id")
        language = state.get("language", "tanglish")

        if not pending_id:
            return {
                "response_message": "No pending action found to confirm.",
                "response_voice_text": "No pending action to confirm.",
                "next_step": "IDLE"
            }

        exec_key = f"AGENT_EXEC_{pending_id}"
        execution_result = None

        if self.pending_svc:
            try:
                result = self.pending_svc.confirm_action(
                    pending_action_id=pending_id,
                    driver_id=driver_id,
                    idempotency_key=exec_key
                )
                execution_result = result
            except Exception as e:
                logger.error("Failed to execute pending action %s: %s", pending_id, e)
                return {
                    "error": str(e),
                    "response_message": f"Execution failed: {str(e)}",
                    "response_voice_text": "Execution failed.",
                    "next_step": "IDLE"
                }
        else:
            execution_result = {"status": "CONFIRMED", "pending_action_id": pending_id}

        proposed = active_action.get("proposed_data", {})
        prompt_data = prompt_execution_success(
            action_type=active_action.get("action_type", "ADD_EXPENSE"),
            amount=proposed.get("amount", "0"),
            category=proposed.get("category", "EXPENSE"),
            vehicle_id=proposed.get("vehicle_id", "DEFAULT_VEHICLE"),
            language=language
        )

        return {
            "active_pending_action": None,
            "execution_result": execution_result,
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "COMPLETED"
        }

    def action_cancellation_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Cancels an active pending action without modifying ledger.
        """
        driver_id = state.get("driver_id", "")
        active_action = state.get("active_pending_action", {})
        pending_id = active_action.get("pending_action_id")
        language = state.get("language", "tanglish")

        if pending_id and self.pending_svc:
            try:
                self.pending_svc.cancel_action(
                    pending_action_id=pending_id,
                    driver_id=driver_id,
                    reason="Driver cancelled via chat"
                )
            except Exception as e:
                logger.warning("Error during cancellation of %s: %s", pending_id, e)

        prompt_data = prompt_cancellation_success(language=language)

        return {
            "active_pending_action": None,
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def query_summary_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Retrieves daily summary from SummaryService.
        """
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")

        if self.summary_svc:
            try:
                summary = self.summary_svc.get_daily_summary(driver_id=driver_id, date_str=today_ist())
                inc = summary.get("total_income", "0.00")
                exp = summary.get("total_expenses", "0.00")
                own = summary.get("total_owner_payments", "0.00")
                net = summary.get("net_balance", "0.00")
            except Exception as e:
                logger.error("Failed to query summary: %s", e)
                inc, exp, own, net = "0.00", "0.00", "0.00", "0.00"
        else:
            inc, exp, own, net = "0.00", "0.00", "0.00", "0.00"

        prompt_data = prompt_daily_summary(
            income=inc,
            expense=exp,
            owner_payment=own,
            net_balance=net,
            language=language
        )

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def query_settlement_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Retrieves settlement status from SettlementService or database.
        """
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")

        rent = "0.00"
        paid = "0.00"
        exp = "0.00"
        bal = "0.00"

        if self.settlement_svc:
            try:
                settlements = self.settlement_svc.get_settlements_for_driver(driver_id=driver_id, limit=1)
                if settlements:
                    s = settlements[0]
                    rent = s.get("rent_expected", "0.00")
                    paid = s.get("actual_owner_payment", "0.00")
                    exp = s.get("operating_expenses_borne_by_driver", "0.00")
                    bal = s.get("remaining_balance", "0.00")
            except Exception as e:
                logger.error("Failed to query settlement: %s", e)

        prompt_data = prompt_settlement_status(
            rent_expected=rent,
            owner_payment=paid,
            expenses_borne=exp,
            balance_due=bal,
            language=language
        )

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def help_node(self, state: AgentState) -> Dict[str, Any]:
        """Provides usage guidance."""
        language = state.get("language", "tanglish")
        prompt_data = prompt_help(language=language)
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def fallback_node(self, state: AgentState) -> Dict[str, Any]:
        """Handles unrecognized queries."""
        language = state.get("language", "tanglish")
        prompt_data = prompt_unknown(language=language)
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }
