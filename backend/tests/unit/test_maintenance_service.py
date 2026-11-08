"""
Unit Tests for Vehicle Maintenance Service.
Verifies maintenance record creation, cost and odometer validation,
upcoming/overdue service schedules, and expenditure summary.
"""

import pytest
import mongomock
from decimal import Decimal

from app.models.maintenance import MaintenanceCategory, normalize_maintenance_category
from app.repositories.maintenance_repository import MaintenanceRepository
from app.services.maintenance_service import MaintenanceService


@pytest.fixture
def maint_fixture():
    db = mongomock.MongoClient().t2t_drive_test
    repo = MaintenanceRepository(db=db)
    svc = MaintenanceService(db=db, maintenance_repo=repo)
    yield svc, repo


def test_category_normalization():
    assert normalize_maintenance_category("Engine Oil Change") == MaintenanceCategory.ENGINE_OIL
    assert normalize_maintenance_category("Brake Shoe Replacement") == MaintenanceCategory.BRAKE_SERVICING
    assert normalize_maintenance_category("Clutch Wire") == MaintenanceCategory.CLUTCH_SERVICING
    assert normalize_maintenance_category("Puncture repair") == MaintenanceCategory.PUNCTURE_REPAIR
    assert normalize_maintenance_category("Tyre replacement") == MaintenanceCategory.TYRE_REPLACEMENT
    assert normalize_maintenance_category("General servicing") == MaintenanceCategory.GENERAL_SERVICING


def test_negative_cost_rejected(maint_fixture):
    svc, _ = maint_fixture

    with pytest.raises(ValueError, match="cost cannot be negative"):
        svc.add_maintenance_record(
            driver_id="DRV_1",
            vehicle_id="TN-09-CB-1284",
            maintenance_category_str="ENGINE_OIL",
            description="Oil change",
            cost=Decimal("-100.00")
        )


def test_negative_odometer_rejected(maint_fixture):
    svc, _ = maint_fixture

    with pytest.raises(ValueError, match="Odometer reading cannot be negative"):
        svc.add_maintenance_record(
            driver_id="DRV_1",
            vehicle_id="TN-09-CB-1284",
            maintenance_category_str="ENGINE_OIL",
            description="Oil change",
            cost=Decimal("450.00"),
            odometer_reading=-500
        )


def test_upcoming_and_overdue_services(maint_fixture):
    svc, _ = maint_fixture

    # Upcoming service next month
    svc.add_maintenance_record(
        driver_id="DRV_SCHED",
        vehicle_id="TN-09-CB-1284",
        maintenance_category_str="ENGINE_OIL",
        description="Upcoming tuneup",
        cost=Decimal("0.00"),
        service_date="2026-11-01",
        next_service_date="2026-12-15",
        next_service_odometer=70000
    )

    # Overdue service last month
    svc.add_maintenance_record(
        driver_id="DRV_SCHED",
        vehicle_id="TN-09-CB-1284",
        maintenance_category_str="BRAKE_SERVICING",
        description="Brake check overdue",
        cost=Decimal("0.00"),
        service_date="2026-09-01",
        next_service_date="2026-10-15",
        next_service_odometer=60000
    )

    upcoming = svc.get_upcoming_services(driver_id="DRV_SCHED", vehicle_id="TN-09-CB-1284")
    assert len(upcoming) >= 1
    assert upcoming[0]["next_service_date"] == "2026-12-15"

    overdue = svc.get_overdue_services(driver_id="DRV_SCHED", vehicle_id="TN-09-CB-1284", current_odometer=65000)
    assert len(overdue) >= 1
    assert overdue[0]["next_service_date"] == "2026-10-15"


def test_spending_summary_aggregation(maint_fixture):
    svc, _ = maint_fixture

    # Add 2 logs: 1 oil change ₹450, 1 brake ₹380
    svc.add_maintenance_record(
        driver_id="DRV_SUMM",
        vehicle_id="TN-09-CB-1284",
        maintenance_category_str="ENGINE_OIL",
        description="Oil change",
        cost=Decimal("450.00"),
        service_date="2026-11-02"
    )
    svc.add_maintenance_record(
        driver_id="DRV_SUMM",
        vehicle_id="TN-09-CB-1284",
        maintenance_category_str="BRAKE_SERVICING",
        description="Brake repair",
        cost=Decimal("380.00"),
        service_date="2026-11-05"
    )

    summary = svc.get_spending_summary(
        driver_id="DRV_SUMM",
        start_date="2026-11-01",
        end_date="2026-11-30"
    )

    assert Decimal(summary["total_spending"]) == Decimal("830.00")
    assert summary["record_count"] == 2
    assert Decimal(summary["by_category"]["ENGINE_OIL"]) == Decimal("450.00")
    assert Decimal(summary["by_category"]["BRAKE_SERVICING"]) == Decimal("380.00")
