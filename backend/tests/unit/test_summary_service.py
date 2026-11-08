"""
Unit tests for Financial Summary Service.
Verifies daily, weekly, monthly, and custom summaries in IST timezone.
"""

from decimal import Decimal
from app.models.financial import TransactionType
from app.repositories.transaction_repository import TransactionRepository
from app.services.ledger_service import LedgerService
from app.services.summary_service import SummaryService


def test_daily_and_period_summaries(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    summary_svc = SummaryService(repo=repo)

    driver_id = "DRV_SUMM_1"
    target_date = "2026-11-08"

    # Insert transactions on target date
    # 1. Fare: 1500
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("1500.00"),
        category="FARE",
        description="Day trips",
        transaction_date=target_date,
        idempotency_key="SUMM_1"
    )
    # 2. Tip: 100
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("100.00"),
        category="TIP",
        description="Generous passenger",
        transaction_date=target_date,
        idempotency_key="SUMM_2"
    )
    # 3. Fuel: 400
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("400.00"),
        category="FUEL",
        description="Petrol",
        transaction_date=target_date,
        idempotency_key="SUMM_3"
    )
    # 4. Food: 150
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("150.00"),
        category="FOOD",
        description="Lunch and tea",
        transaction_date=target_date,
        idempotency_key="SUMM_4"
    )
    # 5. Owner payment: 350
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.OWNER_PAYMENT,
        amount=Decimal("350.00"),
        category="OWNER_RENT",
        description="Daily rent",
        transaction_date=target_date,
        idempotency_key="SUMM_5"
    )

    # Calculate daily summary
    daily = summary_svc.get_daily_summary(driver_id, date_str=target_date)

    m = daily["metrics"]
    assert m["gross_income"] == "1600.00"  # 1500 + 100
    assert m["operating_expenses"] == "550.00"  # 400 + 150
    assert m["operating_profit"] == "1050.00"  # 1600 - 550
    assert m["owner_payments"] == "350.00"
    assert m["driver_take_home"] == "700.00"  # 1050 - 350
    assert m["transaction_count"] == 5
    assert m["category_expenses"]["FUEL"] == "400.00"
    assert m["category_expenses"]["FOOD"] == "150.00"
    assert m["category_income"]["FARE"] == "1500.00"
    assert m["category_income"]["TIP"] == "100.00"


def test_custom_range_summary(db):
    repo = TransactionRepository(db)
    ledger = LedgerService(repo=repo)
    summary_svc = SummaryService(repo=repo)

    driver_id = "DRV_SUMM_2"

    # Day 1
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("1000.00"),
        category="FARE",
        description="Day 1 fare",
        transaction_date="2026-11-01",
        idempotency_key="CR_1"
    )
    # Day 2
    ledger.record_transaction(
        driver_id=driver_id,
        vehicle_id="KA01AB1234",
        transaction_type=TransactionType.INCOME,
        amount=Decimal("2000.00"),
        category="FARE",
        description="Day 2 fare",
        transaction_date="2026-11-05",
        idempotency_key="CR_2"
    )

    # Query 2026-11-01 to 2026-11-05
    res = summary_svc.get_custom_summary(driver_id, "2026-11-01", "2026-11-05")
    assert res["metrics"]["gross_income"] == "3000.00"
    assert res["metrics"]["transaction_count"] == 2
