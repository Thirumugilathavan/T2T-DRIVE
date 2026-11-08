"""
Unit tests for Idempotency Engine.
Verifies at-most-once execution, payload mismatch rejection,
and safe replay of cached responses.
"""

import pytest
from app.services.idempotency_service import (
    IdempotencyService,
    IdempotencyConflictError,
    OperationInProgressError
)
from app.services.audit_service import AuditService


def test_idempotency_lifecycle(db):
    audit = AuditService(db)
    idemp = IdempotencyService(db=db, audit_service=audit)

    driver_id = "DRV_IDEMP_1"
    key = "IDEMP_KEY_001"
    op_type = "PROPOSE_TRANSACTION"
    payload = {"amount": "500.00", "category": "FUEL", "vehicle_id": "KA01AB1234"}

    # 1. Start operation -> Must acquire lock (not cached)
    is_cached, res = idemp.start_operation(driver_id, key, op_type, payload)
    assert is_cached is False
    assert res is None

    # 2. While in progress, duplicate attempt must raise OperationInProgressError
    with pytest.raises(OperationInProgressError):
        idemp.start_operation(driver_id, key, op_type, payload)

    # 3. Complete operation and store cached response
    mock_response = {"success": True, "transaction_id": "TXN_MOCK_1", "amount": "500.00"}
    idemp.complete_operation(driver_id, key, op_type, "TXN_MOCK_1", mock_response)

    # 4. Same key + same payload -> Must return cached response!
    is_cached_2, res_2 = idemp.start_operation(driver_id, key, op_type, payload)
    assert is_cached_2 is True
    assert res_2 == mock_response

    # 5. Same key + DIFFERENT payload -> Must raise IdempotencyConflictError!
    altered_payload = {"amount": "600.00", "category": "FUEL", "vehicle_id": "KA01AB1234"}
    with pytest.raises(IdempotencyConflictError) as exc:
        idemp.start_operation(driver_id, key, op_type, altered_payload)
    assert "was previously used with a different request payload" in str(exc.value)


def test_idempotency_failed_retry(db):
    idemp = IdempotencyService(db=db)
    driver_id = "DRV_IDEMP_2"
    key = "IDEMP_KEY_FAIL"
    op_type = "CONFIRM_TRANSACTION"
    payload = {"action_id": "PEND_123"}

    # Start operation
    is_cached, _ = idemp.start_operation(driver_id, key, op_type, payload)
    assert is_cached is False

    # Mark operation as failed
    idemp.fail_operation(driver_id, key, op_type, "Network timeout")

    # Safe retry: should permit starting again
    is_cached_retry, _ = idemp.start_operation(driver_id, key, op_type, payload)
    assert is_cached_retry is False
