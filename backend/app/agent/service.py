"""
Agent Service and Multi-turn Session Manager for T2T DRIVE.
Manages conversation sessions, message history in MongoDB, LangGraph invocation,
and session-level driver isolation.
"""

import logging
import secrets
from typing import Dict, Any, List, Optional

from app.agent.state import AgentState
from app.agent.nodes import AgentNodes
from app.agent.graph import build_agent_graph
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.agent_service")


class AgentService:
    """
    Orchestrates the LangGraph agent state machine, persists session history
    into MongoDB, and coordinates with financial services.
    """

    def __init__(
        self,
        db,
        pending_action_service=None,
        ledger_service=None,
        summary_service=None,
        settlement_service=None,
        checkpointer=None
    ):
        self.db = db
        self.pending_svc = pending_action_service
        self.ledger_svc = ledger_service
        self.summary_svc = summary_service
        self.settlement_svc = settlement_service

        # Initialize LangGraph node handlers and compile workflow
        self.nodes = AgentNodes(
            pending_action_service=pending_action_service,
            summary_service=summary_service,
            settlement_service=settlement_service,
            db=db
        )
        self.graph = build_agent_graph(self.nodes, checkpointer=checkpointer)

    # ========================================================================
    # SESSION MANAGEMENT
    # ========================================================================

    def create_session(
        self,
        driver_id: str,
        language: str = "tanglish",
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new conversation session record in MongoDB."""
        now = now_utc()
        session_id = f"SESS_{secrets.token_hex(8)}"
        
        # Determine vehicle
        v_id = vehicle_id or self._get_driver_vehicle(driver_id)

        session_doc = {
            "session_id": session_id,
            "driver_id": driver_id,
            "language": language,
            "vehicle_id": v_id,
            "active_pending_action_id": None,
            "turn_count": 0,
            "created_at": now,
            "updated_at": now,
            "status": "ACTIVE"
        }
        self.db.conversation_sessions.insert_one(session_doc)
        logger.info("Created agent session %s for driver %s", session_id, driver_id)
        return self._format_session_doc(session_doc)

    def get_session(self, session_id: str, driver_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves session verifying driver ownership for strict isolation."""
        doc = self.db.conversation_sessions.find_one({"session_id": session_id})
        if not doc:
            return None
        if doc.get("driver_id") != driver_id:
            raise PermissionError(f"Driver '{driver_id}' does not own session '{session_id}'.")
        return self._format_session_doc(doc)

    def list_sessions(self, driver_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Lists recent conversation sessions for a driver."""
        cursor = self.db.conversation_sessions.find(
            {"driver_id": driver_id}
        ).sort("updated_at", -1).limit(limit)
        return [self._format_session_doc(doc) for doc in cursor]

    def get_session_messages(self, session_id: str, driver_id: str) -> List[Dict[str, Any]]:
        """Retrieves message history for a session with driver isolation check."""
        self.get_session(session_id, driver_id)  # Enforce authorization
        cursor = self.db.conversation_messages.find(
            {"session_id": session_id}
        ).sort("timestamp", 1)
        
        messages = []
        for m in cursor:
            m_copy = dict(m)
            m_copy.pop("_id", None)
            messages.append(m_copy)
        return messages

    # ========================================================================
    # MESSAGE PROCESSING
    # ========================================================================

    def process_message(
        self,
        driver_id: str,
        message: str,
        session_id: Optional[str] = None,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a turn of the conversational agent.
        1. Resolves or creates session.
        2. Detects active pending financial actions.
        3. Invokes LangGraph with thread isolation.
        4. Logs turn to conversation_messages.
        5. Updates session state in MongoDB.
        """
        now = now_utc()

        # 1. Resolve session
        if session_id:
            session = self.get_session(session_id, driver_id)
            if not session:
                session = self.create_session(driver_id, language=language or "tanglish")
        else:
            session = self.create_session(driver_id, language=language or "tanglish")

        sid = session["session_id"]
        sess_lang = language or session.get("language", "tanglish")
        vehicle_id = session.get("vehicle_id", "DEFAULT_VEHICLE")

        # 2. Check for active, unexpired pending action for this driver
        active_pending = self._find_active_pending_action(driver_id, session.get("active_pending_action_id"))

        # Preserve session slots across turns
        session_slots = dict(session.get("slots") or {})
        if not session_slots.get("vehicle_id"):
            session_slots["vehicle_id"] = vehicle_id

        # 3. Invoke LangGraph
        config = {"configurable": {"thread_id": sid}}
        input_state: AgentState = {
            "session_id": sid,
            "driver_id": driver_id,
            "language": sess_lang,
            "user_message": message,
            "active_pending_action": active_pending,
            "next_step": session.get("next_step", "IDLE"),
            "intent": session.get("last_intent", ""),
            "slots": session_slots
        }

        result_state = self.graph.invoke(input_state, config=config)

        # 4. Save driver message to audit collection
        user_msg_doc = {
            "message_id": f"MSG_{secrets.token_hex(8)}",
            "session_id": sid,
            "driver_id": driver_id,
            "sender": "DRIVER",
            "text": message,
            "timestamp": now
        }
        self.db.conversation_messages.insert_one(user_msg_doc)

        # 5. Save agent response to audit collection
        agent_msg_doc = {
            "message_id": f"MSG_{secrets.token_hex(8)}",
            "session_id": sid,
            "driver_id": driver_id,
            "sender": "AGENT",
            "text": result_state.get("response_message", ""),
            "voice_text": result_state.get("response_voice_text", ""),
            "intent": result_state.get("intent"),
            "confidence": result_state.get("confidence"),
            "slots": result_state.get("slots"),
            "pending_action_id": (result_state.get("active_pending_action") or {}).get("pending_action_id"),
            "next_step": result_state.get("next_step"),
            "timestamp": now_utc()
        }
        self.db.conversation_messages.insert_one(agent_msg_doc)

        # 6. Update session in MongoDB
        new_pending_id = (result_state.get("active_pending_action") or {}).get("pending_action_id")
        self.db.conversation_sessions.update_one(
            {"session_id": sid},
            {
                "$set": {
                    "updated_at": now_utc(),
                    "language": result_state.get("language", sess_lang),
                    "active_pending_action_id": new_pending_id,
                    "last_intent": result_state.get("intent"),
                    "slots": result_state.get("slots", {}),
                    "next_step": result_state.get("next_step", "IDLE")
                },
                "$inc": {"turn_count": 1}
            }
        )

        # Calculate entities for frontend convenience (frontend/js/voice.js)
        intent = result_state.get("intent")
        slots = result_state.get("slots", {})
        active_pending_res = result_state.get("active_pending_action")

        amt_val = 0.0
        try:
            if active_pending_res and "proposed_data" in active_pending_res:
                amt_val = float(active_pending_res["proposed_data"].get("amount", 0))
            elif "amount" in slots and slots["amount"] is not None:
                amt_val = float(slots["amount"])
        except Exception:
            amt_val = 0.0

        entities = {
            "income": amt_val if intent == "RECORD_INCOME" else 0,
            "expense": amt_val if intent == "RECORD_EXPENSE" else 0,
            "owner_payment": amt_val if intent == "RECORD_OWNER_PAYMENT" else 0,
            "amount": amt_val,
            "category": slots.get("category")
        }

        return {
            "session_id": sid,
            "pending_id": new_pending_id,
            "entities": entities,
            "message": result_state.get("response_message", ""),
            "voice_text": result_state.get("response_voice_text", ""),
            "intent": intent,
            "confidence": result_state.get("confidence", 1.0),
            "language": result_state.get("language", sess_lang),
            "slots": slots,
            "next_step": result_state.get("next_step", "IDLE"),
            "active_pending_action": active_pending_res,
            "execution_result": result_state.get("execution_result"),
            "error": result_state.get("error")
        }

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _find_active_pending_action(self, driver_id: str, action_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Locates active unexpired pending action for driver."""
        now = now_utc()
        query: Dict[str, Any] = {
            "driver_id": driver_id,
            "status": "PENDING",
            "expires_at": {"$gt": now}
        }
        if action_id:
            query["pending_action_id"] = action_id

        doc = self.db.pending_actions.find_one(query)
        if doc and self.pending_svc:
            return self.pending_svc._format_pending_doc(doc)
        elif doc:
            doc_copy = dict(doc)
            doc_copy.pop("_id", None)
            return doc_copy
        return None

    def _get_driver_vehicle(self, driver_id: str) -> str:
        """Looks up driver's assigned vehicle or returns default."""
        v = self.db.vehicles.find_one({"assigned_driver_ids": driver_id, "active_status": "ACTIVE"})
        if v and "registration_number" in v:
            return v["registration_number"]
        return "TN-01-AB-1234"

    @staticmethod
    def _format_session_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Strips MongoDB ObjectId and formats dates for API output."""
        res = dict(doc)
        res.pop("_id", None)
        if "created_at" in res and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        if "updated_at" in res and hasattr(res["updated_at"], "isoformat"):
            res["updated_at"] = res["updated_at"].isoformat()
        return res
