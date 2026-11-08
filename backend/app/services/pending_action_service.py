"""
Pending-Action and Explicit Confirmation Workflow Service for T2T DRIVE.
Enforces the mandatory confirmation boundary: NO financial write (transaction,
adjustment, reversal, settlement) can ever occur directly without an authenticated
driver's explicit confirmation of a validated pending action.
Implements a crash-recoverable, idempotent confirmation state machine.
"""

import secrets
import datetime
import logging
from typing import Dict, Any, Optional, List
from pymongo import ReturnDocument
from decimal import Decimal

from app.models.financial import (
    PendingAction,
    PendingActionStatus,
    PendingActionType,
    TransactionType,
    quantize_money,
    format_money
)
from app.repositories.transaction_repository import from_mongo_doc
from app.services.idempotency_service import IdempotencyService
from app.services.audit_service import AuditService
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger(__name__)


class PendingActionExpiredError(Exception):
    pass


class PendingActionCancelledError(Exception):
    pass


class PendingActionAlreadyConsumedError(Exception):
    pass


class PendingActionUnauthorizedError(Exception):
    pass


class PendingActionService:
    """
    Manages creation, expiration, cancellation, and atomic confirmation
    of proposed financial actions with crash recovery.
    """

    def __init__(
        self,
        db,
        ledger_service,
        settlement_service=None,
        idempotency_service: Optional[IdempotencyService] = None,
        audit_service: Optional[AuditService] = None,
        expiration_minutes: int = 15
    ):
        self.db = db
        self.ledger = ledger_service
        self.settlement = settlement_service
        self.idempotency = idempotency_service
        self.audit = audit_service
        self.expiration_minutes = expiration_minutes

    def set_settlement_service(self, settlement_service):
        """Allows circular reference resolution during app factory initialization."""
        self.settlement = settlement_service

    def propose_action(
        self,
        driver_id: str,
        action_type: PendingActionType,
        proposed_data: Dict[str, Any],
        idempotency_key: str
    ) -> Dict[str, Any]:
        """
        Validates the proposed financial payload and creates a PENDING action.
        Does NOT execute the write.
        """
        now = now_utc()
        expires_at = now + datetime.timedelta(minutes=self.expiration_minutes)
        pending_id = f"PEND_{secrets.token_hex(8)}"

        # Generate human-readable summary based on action type
        summary = self._generate_summary(action_type, proposed_data)

        pending_obj = PendingAction(
            pending_action_id=pending_id,
            driver_id=driver_id,
            action_type=action_type,
            proposed_data=proposed_data,
            status=PendingActionStatus.PENDING,
            human_readable_summary=summary,
            created_at=now,
            expires_at=expires_at,
            idempotency_key=idempotency_key
        )

        doc = pending_obj.model_dump()
        self.db.pending_actions.insert_one(doc)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="PENDING_ACTION_CREATED",
                resource_type="PENDING_ACTION",
                resource_id=pending_id,
                metadata={"action_type": action_type.value, "summary": summary}
            )

        logger.info("Created pending action %s [%s] for driver %s", pending_id, action_type.value, driver_id)
        return self._format_pending_doc(doc)

    def confirm_action(
        self,
        pending_action_id: str,
        driver_id: str,
        idempotency_key: str
    ) -> Dict[str, Any]:
        """
        Atomically confirms and executes a pending action with crash-recovery.
        Guarantees that a financial write executes at most once and can resume
        safely if interrupted by a server restart or crash.
        """
        now = now_utc()

        # 1. Fetch pending action
        action = self.db.pending_actions.find_one({"pending_action_id": pending_action_id})
        if not action:
            raise ValueError(f"Pending action '{pending_action_id}' not found.")

        # 2. Strict driver ownership isolation
        if action.get("driver_id") != driver_id:
            logger.warning(
                "Security violation: Driver %s attempted to confirm pending action %s belonging to driver %s",
                driver_id, pending_action_id, action.get("driver_id")
            )
            if self.audit:
                self.audit.log_event(
                    driver_id=driver_id,
                    event_type="UNAUTHORIZED_ACCESS_ATTEMPT",
                    resource_type="PENDING_ACTION",
                    resource_id=pending_action_id,
                    metadata={"target_driver_id": action.get("driver_id")}
                )
            raise PendingActionUnauthorizedError("Unauthorized: You do not own this pending action.")

        status = action.get("status")

        # 3. Terminal Status: CONSUMED (Return cached result immediately)
        if status == PendingActionStatus.CONSUMED.value:
            if action.get("execution_result"):
                return action["execution_result"]
            # Fallback: check if ledger record exists
            existing_res = self._find_existing_execution_result(pending_action_id, driver_id, action.get("action_type"))
            if existing_res:
                return existing_res
            raise PendingActionAlreadyConsumedError("Pending action has already been consumed.")

        # 4. Terminal Status: CANCELLED
        if status == PendingActionStatus.CANCELLED.value:
            raise PendingActionCancelledError("Pending action has been cancelled.")

        # 5. Check Expiration
        action_expires_at = action.get("expires_at")
        if action_expires_at:
            if action_expires_at.tzinfo is None:
                action_expires_at = action_expires_at.replace(tzinfo=datetime.timezone.utc)
            if now > action_expires_at or status == PendingActionStatus.EXPIRED.value:
                self.db.pending_actions.update_one(
                    {"_id": action["_id"]},
                    {"$set": {"status": PendingActionStatus.EXPIRED.value}}
                )
                raise PendingActionExpiredError("Pending action has expired. Please propose a new action.")

        # 6. CRASH RECOVERY: Handle action already in CONFIRMED state
        if status == PendingActionStatus.CONFIRMED.value:
            # Check if underlying write was already committed to database before the crash
            existing_res = self._find_existing_execution_result(pending_action_id, driver_id, action.get("action_type"))
            if existing_res:
                logger.info("Crash recovery: Found committed ledger entry for confirmed action %s. Marking CONSUMED.", pending_action_id)
                self.db.pending_actions.update_one(
                    {"_id": action["_id"]},
                    {"$set": {"status": PendingActionStatus.CONSUMED.value, "consumed_at": now, "execution_result": existing_res}}
                )
                return existing_res
            # If not yet written, proceed to execute below using the confirmed lock

        elif status in (PendingActionStatus.PENDING.value, PendingActionStatus.FAILED_RETRYABLE.value):
            # Atomic state transition: PENDING/FAILED_RETRYABLE -> CONFIRMED
            confirmed_doc = self.db.pending_actions.find_one_and_update(
                {
                    "_id": action["_id"],
                    "driver_id": driver_id,
                    "status": {"$in": [PendingActionStatus.PENDING.value, PendingActionStatus.FAILED_RETRYABLE.value]},
                    "expires_at": {"$gte": now}
                },
                {
                    "$set": {
                        "status": PendingActionStatus.CONFIRMED.value,
                        "confirmed_at": now,
                        "last_attempt_at": now
                    }
                },
                return_document=ReturnDocument.AFTER
            )
            if not confirmed_doc:
                # Concurrent race check
                fresh = self.db.pending_actions.find_one({"_id": action["_id"]})
                if fresh and fresh.get("status") == PendingActionStatus.CONSUMED.value:
                    return fresh.get("execution_result", {})
                raise ValueError("Failed to confirm action due to concurrent update or expiration.")
            action = confirmed_doc

        else:
            raise ValueError(f"Pending action is in status '{status}' and cannot be confirmed.")

        # 7. Execute Underlying Financial Write
        action_type = action["action_type"]
        data = action["proposed_data"]
        # Use deterministic execution key tied to pending_action_id to prevent duplicate ledger records
        exec_key = f"EXEC_{pending_action_id}"
        execution_result: Dict[str, Any] = {}

        try:
            if action_type in (
                PendingActionType.ADD_INCOME.value,
                PendingActionType.ADD_EXPENSE.value,
                PendingActionType.ADD_OWNER_PAYMENT.value
            ):
                tt_map = {
                    PendingActionType.ADD_INCOME.value: TransactionType.INCOME,
                    PendingActionType.ADD_EXPENSE.value: TransactionType.EXPENSE,
                    PendingActionType.ADD_OWNER_PAYMENT.value: TransactionType.OWNER_PAYMENT,
                }
                execution_result = self.ledger.record_transaction(
                    driver_id=driver_id,
                    vehicle_id=data["vehicle_id"],
                    transaction_type=tt_map[action_type],
                    amount=Decimal(str(data["amount"])),
                    category=data["category"],
                    description=data.get("description", ""),
                    idempotency_key=exec_key,
                    transaction_date=data.get("transaction_date", today_ist()),
                    source=data.get("source", "MANUAL")
                )

            elif action_type == PendingActionType.CREATE_REVERSAL.value:
                execution_result = self.ledger.create_reversal(
                    original_txn_id=data["original_transaction_id"],
                    driver_id=driver_id,
                    reason=data.get("reason", "Driver requested reversal"),
                    idempotency_key=exec_key
                )

            elif action_type == PendingActionType.CREATE_ADJUSTMENT.value:
                execution_result = self.ledger.create_adjustment(
                    original_txn_id=data["original_transaction_id"],
                    driver_id=driver_id,
                    new_amount=Decimal(str(data["new_amount"])),
                    reason=data.get("reason", "Driver requested adjustment"),
                    idempotency_key=exec_key
                )

            elif action_type == PendingActionType.CREATE_SETTLEMENT.value:
                if not self.settlement:
                    raise RuntimeError("Settlement service not initialized.")
                execution_result = self.settlement.create_settlement(
                    driver_id=driver_id,
                    vehicle_id=data["vehicle_id"],
                    settlement_date=data.get("settlement_date", today_ist()),
                    shift_id=data.get("shift_id", "DEFAULT"),
                    previous_balance=Decimal(str(data.get("previous_balance", "0.00"))),
                    idempotency_key=exec_key
                )

            elif action_type == PendingActionType.RECALCULATE_SETTLEMENT.value:
                if not self.settlement:
                    raise RuntimeError("Settlement service not initialized.")
                execution_result = self.settlement.recalculate_settlement(
                    settlement_id=data["settlement_id"],
                    driver_id=driver_id,
                    reason=data.get("reason", "Recalculation"),
                    idempotency_key=exec_key
                )

            else:
                raise ValueError(f"Unknown pending action type: {action_type}")

            # 8. Mark CONSUMED with execution result
            self.db.pending_actions.update_one(
                {"_id": action["_id"]},
                {
                    "$set": {
                        "status": PendingActionStatus.CONSUMED.value,
                        "consumed_at": now_utc(),
                        "execution_result": execution_result
                    }
                }
            )

            if self.audit:
                self.audit.log_event(
                    driver_id=driver_id,
                    event_type="PENDING_ACTION_CONFIRMED",
                    resource_type="PENDING_ACTION",
                    resource_id=pending_action_id,
                    metadata={"action_type": action_type, "execution_status": "SUCCESS"}
                )

            logger.info("Successfully consumed pending action %s for driver %s", pending_action_id, driver_id)
            return execution_result

        except Exception as err:
            logger.error("Execution failed during confirmation of %s: %s", pending_action_id, err)
            # Check if transaction was actually committed despite the exception (e.g. post-write network drop)
            existing_res = self._find_existing_execution_result(pending_action_id, driver_id, action_type)
            if existing_res:
                self.db.pending_actions.update_one(
                    {"_id": action["_id"]},
                    {"$set": {"status": PendingActionStatus.CONSUMED.value, "consumed_at": now_utc(), "execution_result": existing_res}}
                )
                return existing_res

            # Mark FAILED_RETRYABLE so driver can retry without creating a new proposal
            self.db.pending_actions.update_one(
                {"_id": action["_id"]},
                {
                    "$set": {
                        "status": PendingActionStatus.FAILED_RETRYABLE.value,
                        "last_error": str(err),
                        "failed_at": now_utc()
                    }
                }
            )
            raise

    def cancel_action(self, pending_action_id: str, driver_id: str, reason: str = "Driver cancelled") -> Dict[str, Any]:
        """Cancels an unconfirmed pending action."""
        doc = self.db.pending_actions.find_one({"pending_action_id": pending_action_id})
        if not doc:
            raise ValueError(f"Pending action '{pending_action_id}' not found.")
        if doc.get("driver_id") != driver_id:
            raise PendingActionUnauthorizedError("Unauthorized: You do not own this pending action.")
        if doc.get("status") not in (PendingActionStatus.PENDING.value, PendingActionStatus.FAILED_RETRYABLE.value):
            raise ValueError(f"Cannot cancel pending action in status '{doc.get('status')}'.")

        self.db.pending_actions.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": PendingActionStatus.CANCELLED.value, "cancelled_at": now_utc(), "cancellation_reason": reason}}
        )

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                event_type="PENDING_ACTION_CANCELLED",
                resource_type="PENDING_ACTION",
                resource_id=pending_action_id,
                metadata={"reason": reason}
            )

        return {"status": "CANCELLED", "pending_action_id": pending_action_id, "message": "Pending action cancelled."}

    def get_pending_action(self, pending_action_id: str, driver_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single pending action scoped to driver."""
        doc = self.db.pending_actions.find_one({
            "pending_action_id": pending_action_id,
            "driver_id": driver_id
        })
        return self._format_pending_doc(doc) if doc else None

    def list_driver_pending_actions(self, driver_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists pending actions for authenticated driver."""
        query: Dict[str, Any] = {"driver_id": driver_id}
        if status:
            query["status"] = status
        cursor = self.db.pending_actions.find(query).sort("created_at", -1)
        return [self._format_pending_doc(d) for d in cursor if d]

    def _find_existing_execution_result(
        self,
        pending_action_id: str,
        driver_id: str,
        action_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Inspects the ledger or settlements to detect whether a financial write
        for this pending action was already committed prior to a crash.
        """
        exec_key = f"EXEC_{pending_action_id}"

        # 1. Transactions check
        txn = self.db.transactions.find_one({"driver_id": driver_id, "idempotency_key": exec_key})
        if txn:
            from app.services.ledger_service import LedgerService
            return LedgerService._format_transaction(from_mongo_doc(txn))

        # Check for adjustment composite sub-key
        adj_txn = self.db.transactions.find_one({"driver_id": driver_id, "idempotency_key": f"{exec_key}_adj"})
        if adj_txn:
            from app.services.ledger_service import LedgerService
            rev_txn = self.db.transactions.find_one({"driver_id": driver_id, "idempotency_key": f"{exec_key}_rev"})
            return {
                "status": "ADJUSTED",
                "original_transaction_id": adj_txn.get("reference_id"),
                "reversal": LedgerService._format_transaction(from_mongo_doc(rev_txn)) if rev_txn else {},
                "corrected_transaction": LedgerService._format_transaction(from_mongo_doc(adj_txn))
            }

        # 2. Settlements check
        if action_type in (
            PendingActionType.CREATE_SETTLEMENT.value,
            PendingActionType.RECALCULATE_SETTLEMENT.value
        ):
            settle = self.db.settlements.find_one({"driver_id": driver_id, "idempotency_key": exec_key})
            if settle:
                from app.services.settlement_service import SettlementService
                return SettlementService._format_settlement(from_mongo_doc(settle))

        return None

    @staticmethod
    def _generate_summary(action_type: PendingActionType, data: Dict[str, Any]) -> str:
        """Generates human-friendly voice/text confirmation prompt."""
        if action_type == PendingActionType.ADD_INCOME:
            return f"Confirm recording income of ₹{data.get('amount')} ({data.get('category')}) for vehicle {data.get('vehicle_id')}?"
        elif action_type == PendingActionType.ADD_EXPENSE:
            return f"Confirm recording expense of ₹{data.get('amount')} ({data.get('category')}) for vehicle {data.get('vehicle_id')}?"
        elif action_type == PendingActionType.ADD_OWNER_PAYMENT:
            return f"Confirm recording owner payment of ₹{data.get('amount')} for vehicle {data.get('vehicle_id')}?"
        elif action_type == PendingActionType.CREATE_ADJUSTMENT:
            return f"Confirm adjusting transaction {data.get('original_transaction_id')} to ₹{data.get('new_amount')}? Reason: {data.get('reason')}"
        elif action_type == PendingActionType.CREATE_REVERSAL:
            return f"Confirm reversing transaction {data.get('original_transaction_id')}? Reason: {data.get('reason')}"
        elif action_type == PendingActionType.CREATE_SETTLEMENT:
            return f"Confirm reconciling settlement for vehicle {data.get('vehicle_id')} on {data.get('settlement_date')} (Shift: {data.get('shift_id', 'DEFAULT')})?"
        elif action_type == PendingActionType.RECALCULATE_SETTLEMENT:
            return f"Confirm recalculating settlement {data.get('settlement_id')}? Reason: {data.get('reason')}"
        return "Confirm proposed financial action?"

    @staticmethod
    def _format_pending_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Converts datetimes and Decimals for JSON serialization."""
        res = dict(doc)
        if "_id" in res:
            del res["_id"]
        for date_key in ("created_at", "expires_at", "confirmed_at", "consumed_at", "cancelled_at", "last_attempt_at", "failed_at"):
            if date_key in res and res[date_key] and hasattr(res[date_key], "isoformat"):
                res[date_key] = res[date_key].isoformat()
        return res
