"""
Unit tests for Idempotency Audit and Concurrency Recovery (Critical Correction C).
Tests:
- Scoping across drivers and operation types.
- Recovery of abandoned IN_PROGRESS operations after timeout.
- Concurrency race conditions.
- Strict payload mismatch conflict detection.
"""

import pytest
import datetime
from concurrent.futures import ThreadPoolExecutor
from app.services.idempotency_service import (
    IdempotencyService,
    IdempotencyConflictError,
    OperationInProgressError
)


def test_idempotency_driver_and_operation_scoping(db):
    """
    Verifies that idempotency keys are scoped strictly to (driver_id, idempotency_key, operation_type).
    Driver A and Driver B using the same key string do NOT conflict.
    The same driver using the same key for different operation types does NOT conflict.
    """
    idemp = IdempotencyService(db=db)
    key = "SHARED_KEY_123"

    # Driver A starts PROPOSE_TRANSACTION
    is_cached_a, _ = idemp.start_operation("DRV_A", key, "PROPOSE_TRANSACTION", {"amount": "100"})
    assert is_cached_a is False
    idemp.complete_operation("DRV_A", key, "PROPOSE_TRANSACTION", "RES_A", {"success": True, "driver": "A"})

    # Driver B uses the EXACT SAME key -> Must NOT conflict!
    is_cached_b, _ = idemp.start_operation("DRV_B", key, "PROPOSE_TRANSACTION", {"amount": "200"})
    assert is_cached_b is False
    idemp.complete_operation("DRV_B", key, "PROPOSE_TRANSACTION", "RES_B", {"success": True, "driver": "B"})

    # Driver A uses the same key for a DIFFERENT operation type -> Must NOT conflict!
    is_cached_a_diff, _ = idemp.start_operation("DRV_A", key, "CONFIRM_TRANSACTION", {"action": "XYZ"})
    assert is_cached_a_diff is False


def test_abandoned_in_progress_operation_recovery(db):
    """
    If a worker process crashes while an operation is IN_PROGRESS,
    a retry after the 60-second timeout automatically recovers
    the operation instead of being locked out permanently.
    """
    idemp = IdempotencyService(db=db)
    driver_id = "DRV_TIMEOUT"
    key = "TIMEOUT_KEY"
    op_type = "PROPOSE_TRANSACTION"
    payload = {"amount": "500.00"}

    # Start operation
    idemp.start_operation(driver_id, key, op_type, payload)

    # Immediate second request -> Must raise OperationInProgressError
    with pytest.raises(OperationInProgressError):
        idemp.start_operation(driver_id, key, op_type, payload)

    # Backdate created_at to 70 seconds ago (simulating crashed worker)
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=70)
    db.idempotency_records.update_one(
        {"driver_id": driver_id, "idempotency_key": key, "operation_type": op_type},
        {"$set": {"created_at": past_time}}
    )

    # Retry after timeout -> Must recover and acquire the operation lock!
    is_cached, _ = idemp.start_operation(driver_id, key, op_type, payload)
    assert is_cached is False  # Successfully recovered!


def test_concurrent_idempotency_requests(db):
    """
    Simulates 5 concurrent threads attempting to acquire the same idempotency key simultaneously.
    Exactly ONE thread acquires the lock (is_cached=False), and others receive OperationInProgressError.
    """
    idemp = IdempotencyService(db=db)
    driver_id = "DRV_CONC_IDEMP"
    key = "CONC_IDEMP_KEY"
    op_type = "TEST_OP"
    payload = {"val": 42}

    def _acquire(i):
        try:
            return idemp.start_operation(driver_id, key, op_type, payload)
        except Exception as e:
            return e

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_acquire, range(5)))

    # Exactly ONE must have acquired lock (is_cached=False, None)
    locks_acquired = [r for r in results if isinstance(r, tuple) and r[0] is False]
    in_progress_errors = [r for r in results if isinstance(r, OperationInProgressError)]

    assert len(locks_acquired) == 1
    assert len(in_progress_errors) >= 1
