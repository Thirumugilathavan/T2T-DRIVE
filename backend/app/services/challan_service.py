"""
Traffic Challan Service for T2T DRIVE.
Manages challan records, payment settlement logs, attachment uploads,
and optional OCR abstraction with mandatory user confirmation.
"""

import secrets
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal

from app.models.challan import Challan, ChallanStatus
from app.repositories.challan_repository import ChallanRepository
from app.utils.storage import StorageAdapterBase
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.challan_service")


# Official government portal link for informational reference
OFFICIAL_PARIVAHAN_CHALLAN_PORTAL = "https://echallan.parivahan.gov.in"


class OCRAdapterBase(ABC):
    """Abstract interface for Optical Character Recognition on challan notices."""

    @abstractmethod
    def extract_challan_data(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Extracts candidate fields from document.
        Returns: {
            "challan_number": str,
            "registration_number": str,
            "challan_date": str,
            "violation_description": str,
            "fine_amount": str,
            "confidence": float,
            "needs_user_confirmation": True
        }
        """
        pass


class MockOCRAdapter(OCRAdapterBase):
    """
    Mock OCR provider for local development and offline automated testing.
    Extracts structured candidate data from document text or simulated images.
    """

    def extract_challan_data(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        logger.info("[MOCK OCR] Simulating OCR extraction on %s (%d bytes)", filename, len(file_bytes))
        # Simulated untrusted candidate data
        return {
            "challan_number": f"TN09{secrets.token_hex(4).upper()}2026",
            "registration_number": "TN-09-CB-1284",
            "challan_date": today_ist(),
            "issuing_authority": "Chennai City Traffic Police",
            "violation_description": "Traffic Signal Violation (Sec 119/177 MVA)",
            "fine_amount": "500.00",
            "confidence": 0.88,
            "needs_user_confirmation": True,
            "ocr_disclaimer": "OCR data is unverified and requires explicit driver confirmation before saving."
        }


class ChallanService:
    """Manages challan lifecycle, fine payments, and document attachments."""

    def __init__(
        self,
        db,
        challan_repo: ChallanRepository,
        storage: StorageAdapterBase,
        ocr_adapter: Optional[OCRAdapterBase] = None,
        audit_service=None
    ):
        self.db = db
        self.repo = challan_repo
        self.storage = storage
        self.ocr = ocr_adapter or MockOCRAdapter()
        self.audit = audit_service

    def add_challan(
        self,
        driver_id: str,
        challan_number: str,
        vehicle_id: str,
        registration_number: str,
        violation_description: str,
        fine_amount: Decimal,
        challan_date: Optional[str] = None,
        issuing_authority: Optional[str] = None,
        notes: Optional[str] = "",
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        ocr_extracted: bool = False
    ) -> Dict[str, Any]:
        """Creates a new challan record with optional file attachment."""
        file_ref = None
        if file_bytes and filename:
            file_ref, _, _ = self.storage.save_file(file_bytes=file_bytes, original_filename=filename)

        challan_id = f"CHLN_{secrets.token_hex(8)}"
        now = now_utc()

        challan = Challan(
            challan_id=challan_id,
            challan_number=challan_number.strip().upper(),
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            registration_number=registration_number.strip().upper(),
            challan_date=challan_date or today_ist(),
            issuing_authority=issuing_authority or "Traffic Police",
            violation_description=violation_description,
            fine_amount=fine_amount,
            payment_status=ChallanStatus.UNPAID,
            file_reference=file_ref,
            notes=notes or "",
            ocr_extracted=ocr_extracted,
            user_confirmed=True,
            official_verified=False,
            created_at=now,
            updated_at=now
        )

        saved = self.repo.add_challan(challan)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                action="CHALLAN_CREATED",
                resource_type="challan",
                resource_id=challan_id,
                details={"number": challan_number, "fine": str(fine_amount)}
            )

        return self._format_challan_response(saved)

    def extract_from_upload(
        self,
        file_bytes: bytes,
        filename: str
    ) -> Dict[str, Any]:
        """
        Runs OCR on an uploaded notice image/PDF to preview candidate fields.
        Returns candidate fields with explicit unconfirmed status.
        """
        # Save original file first
        file_ref, _, file_type = self.storage.save_file(file_bytes=file_bytes, original_filename=filename)
        ocr_result = self.ocr.extract_challan_data(file_bytes=file_bytes, filename=filename)
        ocr_result["file_reference"] = file_ref
        ocr_result["file_type"] = file_type
        return ocr_result

    def get_challan(self, challan_id: str, driver_id: str) -> Dict[str, Any]:
        """Retrieves challan verifying driver authorization."""
        doc = self.repo.get_by_id(challan_id)
        if not doc:
            raise FileNotFoundError(f"Challan '{challan_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this challan record.")
        return self._format_challan_response(doc)

    def get_challan_file(self, challan_id: str, driver_id: str) -> Tuple[bytes, str]:
        """Retrieves attached notice/receipt binary file."""
        doc = self.repo.get_by_id(challan_id)
        if not doc:
            raise FileNotFoundError(f"Challan '{challan_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this challan record.")

        file_ref = doc.get("file_reference")
        if not file_ref:
            raise FileNotFoundError("No file attached to this challan.")

        return self.storage.get_file(file_ref)

    def list_challans(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists challans for driver with optional filters."""
        docs = self.repo.list_challans(driver_id=driver_id, vehicle_id=vehicle_id, status=status)
        return [self._format_challan_response(d) for d in docs]

    def record_payment(
        self,
        challan_id: str,
        driver_id: str,
        payment_date: str,
        payment_reference: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Records payment for a challan and transitions status to PAID.
        """
        doc = self.repo.get_by_id(challan_id)
        if not doc:
            raise FileNotFoundError(f"Challan '{challan_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this challan record.")

        curr_status = ChallanStatus(doc["payment_status"])
        if curr_status == ChallanStatus.PAID:
            return self._format_challan_response(doc)

        challan_obj = Challan.model_validate(doc)
        if not challan_obj.can_transition_to(ChallanStatus.PAID):
            raise ValueError(f"Cannot transition challan from status '{curr_status.value}' to 'PAID'.")

        updated = self.repo.update_payment(
            challan_id=challan_id,
            payment_date=payment_date,
            payment_reference=payment_reference,
            notes=notes
        )

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                action="CHALLAN_PAID",
                resource_type="challan",
                resource_id=challan_id,
                details={"ref": payment_reference, "date": payment_date}
            )

        return self._format_challan_response(updated)

    def update_status(
        self,
        challan_id: str,
        driver_id: str,
        new_status_str: str,
        reason: Optional[str] = ""
    ) -> Dict[str, Any]:
        """Updates challan status (e.g. DISPUTED, CANCELLED)."""
        doc = self.repo.get_by_id(challan_id)
        if not doc:
            raise FileNotFoundError(f"Challan '{challan_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this challan record.")

        new_status = ChallanStatus(new_status_str.upper())
        challan_obj = Challan.model_validate(doc)
        if not challan_obj.can_transition_to(new_status):
            raise ValueError(f"Invalid status transition from '{challan_obj.payment_status.value}' to '{new_status.value}'.")

        notes = doc.get("notes", "")
        if reason:
            notes = f"{notes} | Status updated to {new_status.value}: {reason}".strip(" |")

        updated = self.repo.update_challan(challan_id, {"payment_status": new_status.value, "notes": notes})
        return self._format_challan_response(updated)

    def _format_challan_response(self, doc_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Formats challan dict for API response."""
        d = dict(doc_dict)
        d["has_file"] = bool(d.get("file_reference"))
        d.pop("file_reference", None)
        d["fine_amount"] = str(d.get("fine_amount", "0.00"))
        d["official_portal_url"] = OFFICIAL_PARIVAHAN_CHALLAN_PORTAL
        return d
