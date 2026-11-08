"""
Deterministic Financial Summary Service for T2T DRIVE.
Aggregates ledger transactions into daily, weekly, monthly, and custom-range summaries
using strict IST calendar boundaries and pure Python Decimal calculations.
"""

from typing import Dict, Any, Optional
from app.repositories.transaction_repository import TransactionRepository
from app.services.financial_calculator import FinancialCalculator
from app.utils.dates import (
    today_ist,
    now_ist,
    get_day_bounds_utc,
    get_week_bounds_utc,
    get_month_bounds_utc,
    parse_date_str
)


class SummaryService:
    """
    Computes deterministic period summaries from the append-only ledger.
    """

    def __init__(self, repo: TransactionRepository):
        self.repo = repo

    def get_daily_summary(
        self,
        driver_id: str,
        date_str: Optional[str] = None,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Returns full financial summary for a single calendar day in IST.
        """
        target_date = (date_str or today_ist()).strip()
        parse_date_str(target_date)  # Validation

        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=target_date,
            end_date=target_date,
            limit=1000  # Full day transactions
        )

        metrics = FinancialCalculator.calculate_metrics(txns)
        start_utc, end_utc = get_day_bounds_utc(target_date)

        return {
            "period": "DAILY",
            "date": target_date,
            "timezone": "Asia/Kolkata",
            "start_time_utc": start_utc.isoformat(),
            "end_time_utc": end_utc.isoformat(),
            "vehicle_id": vehicle_id,
            "metrics": {
                "gross_income": metrics["gross_income"],
                "operating_expenses": metrics["operating_expenses"],
                "operating_profit": metrics["operating_profit"],
                "owner_payments": metrics["owner_payments"],
                "driver_take_home": metrics["driver_take_home"],
                "net_cash_retained": metrics["net_cash_retained"],
                "transaction_count": metrics["transaction_count"],
                "category_expenses": metrics["category_expenses"],
                "category_income": metrics["category_income"]
            }
        }

    def get_weekly_summary(
        self,
        driver_id: str,
        reference_date: Optional[str] = None,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Returns summary for the Monday-to-Sunday week containing reference_date (IST).
        """
        start_utc, end_utc, start_date_ist, end_date_ist = get_week_bounds_utc(reference_date)

        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=start_date_ist,
            end_date=end_date_ist,
            limit=5000
        )

        metrics = FinancialCalculator.calculate_metrics(txns)

        return {
            "period": "WEEKLY",
            "start_date": start_date_ist,
            "end_date": end_date_ist,
            "timezone": "Asia/Kolkata",
            "start_time_utc": start_utc.isoformat(),
            "end_time_utc": end_utc.isoformat(),
            "vehicle_id": vehicle_id,
            "metrics": {
                "gross_income": metrics["gross_income"],
                "operating_expenses": metrics["operating_expenses"],
                "operating_profit": metrics["operating_profit"],
                "owner_payments": metrics["owner_payments"],
                "driver_take_home": metrics["driver_take_home"],
                "net_cash_retained": metrics["net_cash_retained"],
                "transaction_count": metrics["transaction_count"],
                "category_expenses": metrics["category_expenses"],
                "category_income": metrics["category_income"]
            }
        }

    def get_monthly_summary(
        self,
        driver_id: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Returns summary for a specified calendar month in IST.
        """
        current_ist = now_ist()
        y = year or current_ist.year
        m = month or current_ist.month

        start_utc, end_utc, start_date_ist, end_date_ist = get_month_bounds_utc(y, m)

        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=start_date_ist,
            end_date=end_date_ist,
            limit=10000
        )

        metrics = FinancialCalculator.calculate_metrics(txns)

        return {
            "period": "MONTHLY",
            "year": y,
            "month": m,
            "start_date": start_date_ist,
            "end_date": end_date_ist,
            "timezone": "Asia/Kolkata",
            "start_time_utc": start_utc.isoformat(),
            "end_time_utc": end_utc.isoformat(),
            "vehicle_id": vehicle_id,
            "metrics": {
                "gross_income": metrics["gross_income"],
                "operating_expenses": metrics["operating_expenses"],
                "operating_profit": metrics["operating_profit"],
                "owner_payments": metrics["owner_payments"],
                "driver_take_home": metrics["driver_take_home"],
                "net_cash_retained": metrics["net_cash_retained"],
                "transaction_count": metrics["transaction_count"],
                "category_expenses": metrics["category_expenses"],
                "category_income": metrics["category_income"]
            }
        }

    def get_custom_summary(
        self,
        driver_id: str,
        start_date: str,
        end_date: str,
        vehicle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Returns summary for an arbitrary calendar date range [start_date, end_date] inclusive.
        """
        s_date = parse_date_str(start_date)
        e_date = parse_date_str(end_date)
        if s_date > e_date:
            raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date}).")

        txns = self.repo.find_transactions(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            start_date=start_date,
            end_date=end_date,
            limit=10000
        )

        metrics = FinancialCalculator.calculate_metrics(txns)

        return {
            "period": "CUSTOM",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "Asia/Kolkata",
            "vehicle_id": vehicle_id,
            "metrics": {
                "gross_income": metrics["gross_income"],
                "operating_expenses": metrics["operating_expenses"],
                "operating_profit": metrics["operating_profit"],
                "owner_payments": metrics["owner_payments"],
                "driver_take_home": metrics["driver_take_home"],
                "net_cash_retained": metrics["net_cash_retained"],
                "transaction_count": metrics["transaction_count"],
                "category_expenses": metrics["category_expenses"],
                "category_income": metrics["category_income"]
            }
        }
