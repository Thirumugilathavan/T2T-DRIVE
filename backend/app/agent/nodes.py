"""
LangGraph Node Handlers for T2T DRIVE Conversational Agent.
Implements the core state transitions, pending action lifecycle, slot-filling,
summary/settlement retrieval, and Phase 5 document/challan/maintenance assistance.
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
    prompt_unknown,
    prompt_document_expiry,
    prompt_documents_list,
    prompt_unpaid_challans,
    prompt_upcoming_service,
    prompt_trip_started,
    prompt_trip_destination_proposal,
    prompt_trip_stop_proposal,
    prompt_trip_fare_proposal,
    prompt_trip_payment_confirmed
)
from app.models.financial import PendingActionType
from app.models.trip import ProposalType
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
        document_service=None,
        challan_service=None,
        maintenance_service=None,
        trip_service=None,
        trip_reconciliation_service=None,
        db=None
    ):
        self.pending_svc = pending_action_service
        self.summary_svc = summary_service
        self.settlement_svc = settlement_service
        self.document_svc = document_service
        self.challan_svc = challan_service
        self.maintenance_svc = maintenance_service
        self.trip_svc = trip_service
        self.trip_reconciliation_svc = trip_reconciliation_service
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
                elif k == "vehicle_id" and intent in (
                    AgentIntent.CHECK_DOCUMENT_EXPIRY,
                    AgentIntent.LIST_DOCUMENTS,
                    AgentIntent.CHECK_UNPAID_CHALLANS,
                    AgentIntent.LIST_CHALLANS,
                    AgentIntent.CHECK_UPCOMING_SERVICE
                ):
                    merged_slots["vehicle_id"] = None

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
            AgentIntent.ADD_MAINTENANCE: PendingActionType.ADD_EXPENSE,
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

        # If maintenance expense, attach metadata for ledger linkage
        if category == "MAINTENANCE":
            proposed_data["maintenance_details"] = {
                "maintenance_category": "GENERAL_SERVICING",
                "description": slots.get("notes", state.get("user_message", "Vehicle Maintenance")),
                "service_date": today_ist(),
                "service_provider": "Local Garage"
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
            pending_doc = {
                "pending_action_id": f"PEND_MOCK_{secrets.token_hex(6)}",
                "status": "PENDING",
                "proposed_data": proposed_data,
                "action_type": action_type.value
            }

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
        Uses idempotency key AGENT_EXEC_{pending_action_id}.
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
        """Retrieves daily summary from SummaryService."""
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
        """Retrieves settlement status from SettlementService or database."""
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

    # ========================================================================
    # PHASE 5 NODES: DOCUMENTS, CHALLANS, MAINTENANCE
    # ========================================================================

    def query_document_expiry_node(self, state: AgentState) -> Dict[str, Any]:
        """Queries DocumentService for expiry date of specified document."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        doc_type = slots.get("document_type", "INSURANCE")
        vehicle_id = slots.get("vehicle_id")
        if vehicle_id == "DEFAULT_VEHICLE":
            vehicle_id = None

        exp_date = None
        days_left = None

        if self.document_svc:
            try:
                docs = self.document_svc.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
                # Look for matching document
                for d in docs:
                    cur_type = str(d.get("document_type", "")).upper()
                    if cur_type in (doc_type.upper(), f"DOCUMENTTYPE.{doc_type.upper()}"):
                        exp_date = d.get("expiry_date")
                        days_left = d.get("days_left")
                        break
            except Exception as e:
                logger.error("Failed to query document expiry: %s", e)

        prompt_data = prompt_document_expiry(
            doc_type=doc_type,
            expiry_date=exp_date,
            days_left=days_left,
            language=language
        )

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def query_documents_list_node(self, state: AgentState) -> Dict[str, Any]:
        """Queries active documents in driver's vault."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        vehicle_id = state.get("slots", {}).get("vehicle_id")
        if vehicle_id == "DEFAULT_VEHICLE":
            vehicle_id = None

        docs = []
        if self.document_svc:
            try:
                docs = self.document_svc.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
            except Exception as e:
                logger.error("Failed to list documents: %s", e)

        prompt_data = prompt_documents_list(count=len(docs), documents=docs, language=language)

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def query_unpaid_challans_node(self, state: AgentState) -> Dict[str, Any]:
        """Queries unpaid traffic challans."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        vehicle_id = state.get("slots", {}).get("vehicle_id")
        if vehicle_id == "DEFAULT_VEHICLE":
            vehicle_id = None

        unpaid = []
        total_fine = Decimal("0.00")

        if self.challan_svc:
            try:
                unpaid = self.challan_svc.list_challans(driver_id=driver_id, vehicle_id=vehicle_id, status="UNPAID")
                total_fine = sum(Decimal(str(c.get("fine_amount", 0))) for c in unpaid)
            except Exception as e:
                logger.error("Failed to query unpaid challans: %s", e)

        prompt_data = prompt_unpaid_challans(
            count=len(unpaid),
            total_fine=total_fine,
            language=language
        )

        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def query_upcoming_service_node(self, state: AgentState) -> Dict[str, Any]:
        """Queries scheduled future vehicle maintenance."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        vehicle_id = state.get("slots", {}).get("vehicle_id")
        if vehicle_id == "DEFAULT_VEHICLE":
            vehicle_id = None

        service_type = None
        next_date = None
        next_km = None

        if self.maintenance_svc:
            try:
                upcoming = self.maintenance_svc.get_upcoming_services(driver_id=driver_id, vehicle_id=vehicle_id)
                if upcoming:
                    first = upcoming[0]
                    service_type = first.get("category_label") or first.get("description")
                    next_date = first.get("next_service_date")
                    next_km = first.get("next_service_odometer")
            except Exception as e:
                logger.error("Failed to query upcoming maintenance: %s", e)

        prompt_data = prompt_upcoming_service(
            service_type=service_type,
            next_date=next_date,
            next_km=next_km,
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

    # ========================================================================
    # PASSENGER EXTENSION NODES: TRIPS, PROPOSALS & RECONCILIATION
    # ========================================================================

    def start_trip_node(self, state: AgentState) -> Dict[str, Any]:
        """Creates and initiates a new trip with passenger agreement."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        destination = slots.get("destination") or "Destination"
        fare = slots.get("fare") or slots.get("amount") or Decimal("100.00")
        vehicle_id = slots.get("vehicle_id") or "TN-01-AB-1234"

        trip_id = f"TRIP_MOCK_{secrets.token_hex(4)}"
        if self.trip_svc:
            try:
                trip = self.trip_svc.create_trip(
                    driver_id=driver_id,
                    vehicle_id=vehicle_id,
                    destination=destination,
                    initial_fare=fare
                )
                trip_id = trip["trip_id"]
            except Exception as e:
                logger.error("Failed to create trip via agent: %s", e)

        prompt_data = prompt_trip_started(
            trip_id=trip_id,
            destination=destination,
            fare=fare,
            language=language
        )
        return {
            "trip_id": trip_id,
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def trip_destination_node(self, state: AgentState) -> Dict[str, Any]:
        """Proposes a destination change for an active trip."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        new_dest = slots.get("destination") or slots.get("new_destination") or "New Destination"

        if self.trip_svc:
            try:
                active_trip = self.trip_svc.get_active_trip_for_driver(driver_id)
                if active_trip:
                    self.trip_svc.propose_change(
                        trip_id=active_trip["trip_id"],
                        proposer_role="DRIVER",
                        proposal_type=ProposalType.DESTINATION_CHANGE,
                        proposed_changes={"destination": new_dest}
                    )
            except Exception as e:
                logger.error("Failed to propose destination change: %s", e)

        prompt_data = prompt_trip_destination_proposal(new_destination=new_dest, language=language)
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def trip_stop_node(self, state: AgentState) -> Dict[str, Any]:
        """Proposes an intermediate stop for an active trip."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        stop_name = slots.get("stop_name") or slots.get("notes") or "Intermediate Stop"

        if self.trip_svc:
            try:
                active_trip = self.trip_svc.get_active_trip_for_driver(driver_id)
                if active_trip:
                    self.trip_svc.propose_change(
                        trip_id=active_trip["trip_id"],
                        proposer_role="DRIVER",
                        proposal_type=ProposalType.ADD_STOP,
                        proposed_changes={"stop_name": stop_name}
                    )
            except Exception as e:
                logger.error("Failed to propose additional stop: %s", e)

        prompt_data = prompt_trip_stop_proposal(stop_name=stop_name, language=language)
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def trip_fare_node(self, state: AgentState) -> Dict[str, Any]:
        """Proposes a fare change for an active trip."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        new_fare = slots.get("fare") or slots.get("amount") or Decimal("150.00")

        if self.trip_svc:
            try:
                active_trip = self.trip_svc.get_active_trip_for_driver(driver_id)
                if active_trip:
                    self.trip_svc.propose_change(
                        trip_id=active_trip["trip_id"],
                        proposer_role="DRIVER",
                        proposal_type=ProposalType.FARE_CHANGE,
                        proposed_changes={"fare": str(new_fare)}
                    )
            except Exception as e:
                logger.error("Failed to propose fare change: %s", e)

        prompt_data = prompt_trip_fare_proposal(new_fare=new_fare, language=language)
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }

    def trip_payment_node(self, state: AgentState) -> Dict[str, Any]:
        """Records a trip fare payment and executes financial reconciliation."""
        driver_id = state.get("driver_id", "")
        language = state.get("language", "tanglish")
        slots = state.get("slots", {})
        amount = slots.get("amount") or Decimal("100.00")
        method = slots.get("payment_method") or "CASH"
        outstanding = Decimal("0.00")

        if self.trip_reconciliation_svc and self.trip_svc:
            try:
                active_trip = self.trip_svc.get_active_trip_for_driver(driver_id)
                if active_trip:
                    res = self.trip_reconciliation_svc.record_trip_payment(
                        trip_id=active_trip["trip_id"],
                        driver_id=driver_id,
                        amount=Decimal(str(amount)),
                        payment_method=method,
                        idempotency_key=f"VOICE_PAY_{active_trip['trip_id']}_{secrets.token_hex(4)}"
                    )
                    outstanding = res.get("outstanding_amount", Decimal("0.00"))
            except Exception as e:
                logger.error("Failed to record trip payment via agent: %s", e)

        prompt_data = prompt_trip_payment_confirmed(
            amount=amount,
            outstanding=outstanding,
            language=language
        )
        return {
            "response_message": prompt_data["text"],
            "response_voice_text": prompt_data["voice"],
            "next_step": "IDLE"
        }
