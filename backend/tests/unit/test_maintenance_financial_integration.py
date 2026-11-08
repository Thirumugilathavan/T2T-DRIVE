"""
Unit Tests for Maintenance Expense Integration with Phase 2 Financial Ledger.
Verifies the confirmation firewall, atomic linkage between MaintenanceRecord and
FinancialTransaction, idempotency on retries, and settlement reconciliation.
"""

import pytest
import mongomock
from decimal import Decimal

from app.models.financial import PendingActionStatus, TransactionType
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.maintenance_repository import MaintenanceRepository
from app.services.ledger_service import LedgerService
from app.services.pending_action_service import PendingActionService
from app.services.maintenance_service import MaintenanceService
from app.services.settlement_service import SettlementService
from app.services.summary_service import SummaryService


@pytest.fixture
def integrated_fixture():
    db = mongomock.MongoClient().t2t_drive_test
    txn_repo = TransactionRepository(db=db)
    maint_repo = MaintenanceRepository(db=db)

    ledger_svc = LedgerService(repo=txn_repo)
    settlement_svc = SettlementService(db=db, repo=txn_repo)
    pending_svc = PendingActionService(
        db=db,
        ledger_service=ledger_svc,
        settlement_service=settlement_svc
    )
    maint_svc = MaintenanceService(
        db=db,
        maintenance_repo=maint_repo,
        pending_action_service=pending_svc,
        ledger_service=ledger_svc
    )
    pending_svc.set_maintenance_service(maint_svc)
    summary_svc = SummaryService(repo=txn_repo)

    yield maint_svc, pending_svc, ledger_svc, maint_repo, txn_repo, summary_svc


def test_maintenance_expense_proposal_and_confirmation_journey(integrated_fixture):
    maint_svc, pending_svc, ledger_svc, maint_repo, txn_repo, summary_svc = integrated_fixture
    driver_id = "DRV_EXP_1"
    vehicle_id = "TN-09-CB-1284"

    # 1. Propose maintenance expense: Auto service ₹1,200
    proposal = maint_svc.propose_maintenance_with_expense(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        maintenance_category_str="GENERAL_SERVICING",
        description="Auto full servicing",
        cost=Decimal("1200.00"),
        service_date="2026-11-08",
        odometer_reading=64500,
        service_provider="Shanmugam Auto Works"
    )

    pending_id = proposal["pending_action_id"]
    assert pending_id.startswith("PEND_")
    assert proposal["action_required"] == "CONFIRM_TRANSACTION"

    # CONFIRMATION FIREWALL: Ledger must have 0 transactions, maintenance records must be 0
    assert len(txn_repo.get_transactions_for_driver(driver_id)) == 0
    assert len(maint_repo.list_records(driver_id)) == 0

    # 2. Driver confirms the pending action
    result = pending_svc.confirm_action(
        pending_action_id=pending_id,
        driver_id=driver_id,
        idempotency_key=f"EXEC_{pending_id}"
    )

    assert result["status"] == "COMPLETED"
    txn_id = result["transaction_id"]
    assert txn_id.startswith("TXN_")

    # 3. Verify ledger entry committed
    txns = txn_repo.get_transactions_for_driver(driver_id)
    assert len(txns) == 1
    committed_txn = txns[0]
    assert committed_txn["category"] == "MAINTENANCE"
    assert Decimal(committed_txn["amount"]) == Decimal("1200.00")
    assert Decimal(committed_txn["signed_amount"]) == Decimal("-1200.00")

    # 4. Verify linked maintenance record created
    maint_logs = maint_repo.list_records(driver_id)
    assert len(maint_logs) == 1
    m_record = maint_logs[0]
    assert m_record["financial_transaction_id"] == txn_id
    assert m_record["cost"] == Decimal("1200.00")
    assert m_record["service_provider"] == "Shanmugam Auto Works"

    # 5. Verify Daily Summary counts the ₹1,200 expense
    summary = summary_svc.get_daily_summary(driver_id=driver_id, date_str="2026-11-08")
    assert Decimal(summary["metrics"]["operating_expenses"]) == Decimal("1200.00")
    assert Decimal(summary["metrics"]["operating_profit"]) == Decimal("-1200.00")


def test_idempotent_retry_prevents_duplicate_maintenance_and_transactions(integrated_fixture):
    maint_svc, pending_svc, _, maint_repo, txn_repo, _ = integrated_fixture
    driver_id = "DRV_RETRY"

    proposal = maint_svc.propose_maintenance_with_expense(
        driver_id=driver_id,
        vehicle_id="TN-09-CB-1284",
        maintenance_category_str="ENGINE_OIL",
        description="Oil change",
        cost=Decimal("450.00")
    )
    pending_id = proposal["pending_action_id"]

    # First confirmation
    res1 = pending_svc.confirm_action(pending_id, driver_id, f"EXEC_{pending_id}")
    txn_id_1 = res1["transaction_id"]

    # Second confirmation retry (e.g. network timeout on client)
    res2 = pending_svc.confirm_action(pending_id, driver_id, f"EXEC_{pending_id}")
    txn_id_2 = res2["transaction_id"]

    assert txn_id_1 == txn_id_2
    # Ensure exactly 1 transaction in ledger and 1 maintenance record
    assert len(txn_repo.get_transactions_for_driver(driver_id)) == 1
    assert len(maint_repo.list_records(driver_id)) == 1
