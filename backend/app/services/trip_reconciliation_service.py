"""
Trip Payment Reconciliation and Ledger Integration Engine for T2T DRIVE.
Integrates trip fare collections with the Phase 2 Append-Only Financial Ledger,
enforces the Earned vs. Collected boundary, prevents revenue double-counting,
and guarantees owner-driver vehicle settlements remain unaffected.
"""

import secrets
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal

from app.models.trip import (
    Trip,
    TripPayment,
    TripPaymentStatus,
    PaymentMethod,
    TripState
)
from app.models.financial import (
    TransactionType,
    quantize_money,
    format_money
)
from app.repositories.trip_repository import TripRepository
from app.services.ledger_service import LedgerService
from app.services.idempotency_service import IdempotencyService
from app.services.passenger_access_service import PassengerAccessService
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.trip_reconciliation")


class TripPaymentValidationError(Exception):
    pass


class TripReconciliationService:
    """
    Coordinates passenger trip payments with the core append-only financial ledger.
    Maintains three strictly isolated accounting concepts:
    1. Driver Earnings (Ledger Income)
    2. Driver-Passenger Trip Receivables (Earned vs. Collected)
    3. Driver-Owner Vehicle Settlement (Unaffected by passenger receivables)
    """

    def __init__(
        self,
        repository: TripRepository,
        ledger_service: LedgerService,
        idempotency_service: IdempotencyService,
        passenger_access_service: PassengerAccessService
    ):
        self.repo = repository
        self.ledger = ledger_service
        self.idempotency = idempotency_service
        self.access_svc = passenger_access_service

    def record_trip_payment(
        self,
        trip_id: str,
        amount: Decimal,
        payment_method: PaymentMethod,
        idempotency_key: str,
        driver_id: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Records a cash or UPI passenger payment towards an agreed trip fare.
        Enforces:
        - Atomic idempotency locking to prevent double-charging/double-collection on network retry.
        - Earned vs. Collected math (receivable reduction without inflating gross earned fare).
        - Direct append-only entry into the immutable financial ledger.
        """
        amt = quantize_money(amount)
        if amt <= Decimal("0.00"):
            raise TripPaymentValidationError("Payment amount must be greater than zero.")

        # 1. Idempotency Check & Lock
        is_cached, cached_result = self.idempotency.start_operation(
            driver_id=driver_id,
            idempotency_key=idempotency_key,
            operation_type="RECORD_TRIP_PAYMENT",
            payload={"trip_id": trip_id, "amount": str(amt), "method": payment_method.value}
        )
        if is_cached and cached_result is not None:
            logger.info("Idempotent replay for trip payment %s on trip %s", idempotency_key, trip_id)
            return cached_result

        # 2. Retrieve Trip
        trip_doc = self.repo.get_trip(trip_id)
        if not trip_doc:
            raise ValueError(f"Trip {trip_id} not found.")

        trip = Trip(**trip_doc)
        if trip.driver_id != driver_id:
            raise PermissionError("Driver unauthorized to record payment on this trip.")

        if trip.state == TripState.CANCELLED:
            raise TripPaymentValidationError("Cannot record payments on a cancelled trip.")

        # 3. Calculate New Balances
        new_collected = quantize_money(trip.collected_amount + amt)
        new_outstanding = quantize_money(max(Decimal("0.00"), trip.earned_fare - new_collected))

        if new_outstanding == Decimal("0.00"):
            new_payment_status = TripPaymentStatus.PAID
            next_state = TripState.COMPLETED if trip.state == TripState.PAYMENT_PENDING else trip.state
        else:
            new_payment_status = TripPaymentStatus.PARTIALLY_PAID
            next_state = trip.state

        now_str = now_utc()
        payment_id = f"PAY_{secrets.token_hex(8)}"

        # 4. Append to Financial Ledger (Single Source of Truth)
        # Note: Ledger transaction uses category="TRIP_FARE" and stores trip_id in reference_id
        txn_res = self.ledger.record_transaction(
            driver_id=driver_id,
            vehicle_id=trip.vehicle_id,
            transaction_type=TransactionType.INCOME,
            amount=amt,
            category="TRIP_FARE",
            description=f"Passenger payment collected ({payment_method.value}) for trip {trip_id}",
            idempotency_key=idempotency_key,
            transaction_date=today_ist(),
            source="TRIP_PAYMENT",
            reference_id=trip_id,
            created_by="DRIVER"
        )

        txn_id = txn_res["transaction_id"]

        # 5. Record Individual Payment Document
        payment_record = TripPayment(
            payment_id=payment_id,
            trip_id=trip_id,
            driver_id=driver_id,
            amount=amt,
            payment_method=payment_method,
            transaction_id=txn_id,
            collected_at=now_str,
            notes=notes
        )
        self.repo.insert_payment(payment_record.model_dump())

        # 6. Update Trip Document
        updates = {
            "collected_amount": new_collected,
            "outstanding_amount": new_outstanding,
            "payment_status": new_payment_status.value,
            "payment_method": payment_method.value,
            "state": next_state.value,
            "updated_at": now_str
        }
        self.repo.update_trip(trip_id, updates)

        # 7. Record Audit Event
        event_desc = (
            f"Collected ₹{amt} via {payment_method.value}. "
            f"Total Collected: ₹{new_collected}, Outstanding: ₹{new_outstanding} ({new_payment_status.value})"
        )
        self.repo.insert_event({
            "event_id": f"EVT_{secrets.token_hex(8)}",
            "trip_id": trip_id,
            "event_type": "PAYMENT_COLLECTED",
            "source": "DRIVER",
            "description": event_desc,
            "metadata": {
                "payment_id": payment_id,
                "amount": format_money(amt),
                "method": payment_method.value,
                "ledger_txn_id": txn_id
            },
            "timestamp": now_str
        })

        result = {
            "payment_id": payment_id,
            "trip_id": trip_id,
            "amount_paid": format_money(amt),
            "payment_method": payment_method.value,
            "total_collected": format_money(new_collected),
            "outstanding_amount": format_money(new_outstanding),
            "payment_status": new_payment_status.value,
            "ledger_transaction_id": txn_id
        }

        # Cache in idempotency record
        self.idempotency.complete_operation(
            driver_id=driver_id,
            idempotency_key=idempotency_key,
            operation_type="RECORD_TRIP_PAYMENT",
            response_data=result,
            resource_id=payment_id
        )

        return result

    def generate_passenger_receipt(
        self,
        trip_id: str,
        raw_token: str
    ) -> Dict[str, Any]:
        """
        Generates a transparent, mobile-friendly passenger digital trip receipt.
        Excludes driver internal financial summaries and vehicle owner settlements.
        """
        self.access_svc.validate_passenger_token(trip_id, raw_token)
        trip_doc = self.repo.get_trip(trip_id)
        if not trip_doc:
            raise ValueError(f"Trip {trip_id} not found.")

        trip = Trip(**trip_doc)
        payments = self.repo.list_payments_for_trip(trip_id)

        # Compile agreed version history
        agreements = [a.to_dict() for a in trip.agreement_history]

        date_val = trip.created_at.strftime("%Y-%m-%d") if hasattr(trip.created_at, "strftime") else str(trip.created_at)[:10]
        agreed_val = format_money(trip.current_agreed_fare) if trip.current_agreed_fare else "UNAGREED"
        paid_val = format_money(trip.collected_amount)

        return {
            "receipt_type": "SHARED_DIGITAL_TRIP_RECEIPT",
            "disclaimer": "This receipt is a transparent shared trip record generated by T2T DRIVE. Not a statutory tax invoice.",
            "trip_id": trip.trip_id,
            "vehicle_id": trip.vehicle_id,
            "date": date_val,
            "pickup_location": trip.pickup_location,
            "destination_location": trip.destination_location,
            "additional_stops": list(trip.additional_stops),
            "initial_proposed_fare": format_money(trip.initial_proposed_fare),
            "final_agreed_fare": agreed_val,
            "agreed_fare": agreed_val,
            "total_amount_paid": paid_val,
            "total_paid": paid_val,
            "paid_amount": paid_val,
            "outstanding_amount": format_money(trip.outstanding_amount),
            "payment_status": trip.payment_status.value,
            "payment_method": trip.payment_method.value if trip.payment_method else None,
            "payments_history": [
                {
                    "payment_id": p.get("payment_id"),
                    "amount": format_money(p.get("amount")),
                    "method": p.get("payment_method"),
                    "collected_at": p.get("collected_at")
                }
                for p in payments
            ],
            "agreement_versions": agreements,
            "trip_status": trip.state.value,
            "completed_at": trip.completed_at
        }
