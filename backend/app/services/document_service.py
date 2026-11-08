"""
Document Service for T2T DRIVE.
Manages driver and vehicle document lifecycles, ownership validation,
secure file uploads, expiry status calculations, and renewal superseding.
"""

import secrets
import logging
from typing import Dict, Any, List, Optional, Tuple
import datetime

from app.models.vehicle_document import (
    VehicleDocument,
    DocumentType,
    ExpiryStatus,
    VerificationStatus,
    normalize_document_type,
    VEHICLE_DOC_TYPES
)
from app.repositories.document_repository import DocumentRepository
from app.utils.storage import StorageAdapterBase
from app.utils.dates import now_utc, today_ist

logger = logging.getLogger("t2t_drive.document_service")


def mask_document_number(num: Optional[str]) -> Optional[str]:
    """Masks document number for privacy, showing only first and last characters."""
    if not num:
        return None
    clean = str(num).strip()
    if len(clean) <= 4:
        return clean
    if len(clean) <= 8:
        return clean[:2] + "****" + clean[-2:]
    return clean[:4] + "****" + clean[-4:]


class DocumentService:
    """Orchestrates document CRUD, security checks, and expiry calculations."""

    def __init__(
        self,
        db,
        document_repo: DocumentRepository,
        storage: StorageAdapterBase,
        reminder_repo=None,
        audit_service=None
    ):
        self.db = db
        self.repo = document_repo
        self.storage = storage
        self.reminder_repo = reminder_repo
        self.audit = audit_service

    def _verify_vehicle_ownership(self, driver_id: str, vehicle_id: Optional[str]) -> bool:
        """
        Verifies if driver is assigned to the vehicle in MongoDB.
        Returns True if assigned or if vehicle is not yet registered in development mode.
        """
        if not vehicle_id:
            return True

        if self.db is None:
            return True

        # Check vehicle collection
        vehicle = self.db.vehicles.find_one({"vehicle_id": vehicle_id})
        if not vehicle:
            # Also check by registration_number
            vehicle = self.db.vehicles.find_one({"registration_number": vehicle_id})

        if vehicle:
            assigned = vehicle.get("assigned_driver_ids", [])
            owner = vehicle.get("owner_id")
            if driver_id in assigned or driver_id == owner:
                return True
            return False

        # If vehicle not explicitly in vehicles collection, permit in dev/testing
        return True

    def add_document(
        self,
        driver_id: str,
        document_type_str: str,
        document_number: Optional[str] = None,
        expiry_date: Optional[str] = None,
        vehicle_id: Optional[str] = None,
        issue_date: Optional[str] = None,
        issuing_authority: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        notes: Optional[str] = ""
    ) -> Dict[str, Any]:
        """
        Registers a new document with validation and optional file upload.
        If an active document of the same type exists for this vehicle, marks the old one superseded.
        """
        doc_type = normalize_document_type(document_type_str)

        # Vehicle ownership check for vehicle-specific documents
        if doc_type in VEHICLE_DOC_TYPES and vehicle_id:
            if not self._verify_vehicle_ownership(driver_id, vehicle_id):
                raise PermissionError(f"Driver '{driver_id}' is not authorized to register documents for vehicle '{vehicle_id}'.")

        # Handle file upload if present
        file_ref = None
        file_size = None
        file_type = None

        if file_bytes and filename:
            file_ref, file_size, file_type = self.storage.save_file(
                file_bytes=file_bytes,
                original_filename=filename
            )

        doc_id = f"DOC_{secrets.token_hex(8)}"
        now = now_utc()

        # Check for existing active document of the same type to supersede
        existing_docs = self.repo.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
        for existing in existing_docs:
            if existing.get("document_type") == doc_type.value:
                old_id = existing["document_id"]
                logger.info("Renewing document type %s: Superseding old document %s with new %s", doc_type.value, old_id, doc_id)
                self.repo.supersede_document(old_document_id=old_id, new_document_id=doc_id)
                # Dismiss previous document's pending reminders
                if self.reminder_repo:
                    self.reminder_repo.cancel_reminders_for_reference(old_id)

        doc_model = VehicleDocument(
            document_id=doc_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            document_type=doc_type,
            document_number=document_number,
            issuing_authority=issuing_authority,
            issue_date=issue_date,
            expiry_date=expiry_date,
            file_reference=file_ref,
            file_type=file_type,
            file_size_bytes=file_size,
            upload_timestamp=now,
            verification_status=VerificationStatus.UNVERIFIED,
            notes=notes or "",
            is_active=True,
            created_at=now,
            updated_at=now
        )

        saved = self.repo.add_document(doc_model)

        if self.audit:
            self.audit.log_event(
                driver_id=driver_id,
                action="DOCUMENT_CREATED",
                resource_type="document",
                resource_id=doc_id,
                details={"type": doc_type.value, "vehicle_id": vehicle_id, "has_file": bool(file_ref)}
            )

        return self._format_document_response(saved)

    def get_document(self, document_id: str, driver_id: str) -> Dict[str, Any]:
        """Retrieves document verifying driver ownership."""
        doc = self.repo.get_by_id(document_id)
        if not doc:
            raise FileNotFoundError(f"Document '{document_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this document.")
        return self._format_document_response(doc)

    def get_document_file(self, document_id: str, driver_id: str) -> Tuple[bytes, str]:
        """Retrieves binary document file verifying driver authorization."""
        doc = self.repo.get_by_id(document_id)
        if not doc:
            raise FileNotFoundError(f"Document '{document_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this document.")

        file_ref = doc.get("file_reference")
        if not file_ref:
            raise FileNotFoundError("This document does not have an attached file.")

        return self.storage.get_file(file_ref)

    def list_documents(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Lists documents for a driver, enriched with expiry status."""
        docs = self.repo.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=active_only)
        return [self._format_document_response(d) for d in docs]

    def update_document(
        self,
        document_id: str,
        driver_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Updates document metadata verifying authorization."""
        doc = self.repo.get_by_id(document_id)
        if not doc:
            raise FileNotFoundError(f"Document '{document_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this document.")

        allowed_fields = {"document_number", "issuing_authority", "issue_date", "expiry_date", "notes"}
        clean_updates = {k: v for k, v in updates.items() if k in allowed_fields and v is not None}

        updated = self.repo.update_metadata(document_id, clean_updates)
        return self._format_document_response(updated)

    def replace_document_file(
        self,
        document_id: str,
        driver_id: str,
        file_bytes: bytes,
        filename: str
    ) -> Dict[str, Any]:
        """Replaces the uploaded file of an existing document."""
        doc = self.repo.get_by_id(document_id)
        if not doc:
            raise FileNotFoundError(f"Document '{document_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this document.")

        # Save new file
        new_ref, size, mime = self.storage.save_file(file_bytes=file_bytes, original_filename=filename)

        # Delete previous file if exists
        old_ref = doc.get("file_reference")
        if old_ref:
            self.storage.delete_file(old_ref)

        updates = {
            "file_reference": new_ref,
            "file_size_bytes": size,
            "file_type": mime,
            "upload_timestamp": now_utc(),
            "updated_at": now_utc()
        }
        updated = self.repo.update_metadata(document_id, updates)
        return self._format_document_response(updated)

    def delete_document(self, document_id: str, driver_id: str) -> bool:
        """Marks document inactive (soft delete)."""
        doc = self.repo.get_by_id(document_id)
        if not doc:
            raise FileNotFoundError(f"Document '{document_id}' not found.")
        if doc["driver_id"] != driver_id:
            raise PermissionError("Access denied: You do not own this document.")

        if self.reminder_repo:
            self.reminder_repo.cancel_reminders_for_reference(document_id)

        return self.repo.mark_inactive(document_id)

    def get_compliance_status(self, driver_id: str, vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        """Computes compliance status badge & counts for the fleet dashboard."""
        docs = self.list_documents(driver_id=driver_id, vehicle_id=vehicle_id, active_only=True)
        total = len(docs)
        expired = 0
        critical = 0  # <= 7 days
        warning = 0   # <= 30 days
        active = 0

        for d in docs:
            days = d.get("days_left")
            if days is None:
                continue
            if days < 0:
                expired += 1
            elif days <= 7:
                critical += 1
            elif days <= 30:
                warning += 1
            else:
                active += 1

        total_alerts = expired + critical + warning
        status = "CRITICAL" if (expired > 0 or critical > 0) else ("WARNING" if warning > 0 else "SAFE")

        return {
            "total_documents": total,
            "expired_count": expired,
            "critical_count": critical,
            "warning_count": warning,
            "active_count": active,
            "total_alerts": total_alerts,
            "compliance_status": status
        }

    def _format_document_response(self, doc_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Formats document document dict for API output."""
        d = dict(doc_dict)
        doc_obj = VehicleDocument.model_validate(d)
        exp_status, days_left = doc_obj.calculate_expiry_status()

        d["expiry_status"] = exp_status.value
        d["days_left"] = days_left
        d["has_file"] = bool(d.get("file_reference"))
        d["document_number_masked"] = mask_document_number(d.get("document_number"))
        # Do not expose raw storage path
        d.pop("file_reference", None)
        return d
