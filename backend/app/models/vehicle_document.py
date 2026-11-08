"""
Vehicle and Driver Document Domain Models for T2T DRIVE.
Enforces strict document categories, validity checks, expiry calculations,
and multi-state lifecycle management (ACTIVE, EXPIRING_SOON, EXPIRED, UNKNOWN).
"""

from enum import Enum
from typing import Optional, Any, Tuple
import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.utils.dates import now_utc, today_ist


class DocumentType(str, Enum):
    # Vehicle documents
    RC = "RC"
    INSURANCE = "INSURANCE"
    FITNESS = "FITNESS"
    PUC = "PUC"
    PERMIT = "PERMIT"
    TAX_RECEIPT = "TAX_RECEIPT"
    OTHER_VEHICLE = "OTHER_VEHICLE"

    # Driver documents
    DRIVING_LICENCE = "DRIVING_LICENCE"
    BADGE = "BADGE"
    OTHER_DRIVER = "OTHER_DRIVER"


class ExpiryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


# Document Category Mapping Helper
VEHICLE_DOC_TYPES = {
    DocumentType.RC,
    DocumentType.INSURANCE,
    DocumentType.FITNESS,
    DocumentType.PUC,
    DocumentType.PERMIT,
    DocumentType.TAX_RECEIPT,
    DocumentType.OTHER_VEHICLE,
}

DRIVER_DOC_TYPES = {
    DocumentType.DRIVING_LICENCE,
    DocumentType.BADGE,
    DocumentType.OTHER_DRIVER,
}


def normalize_document_type(raw_type: str) -> DocumentType:
    """
    Normalizes human-friendly strings (e.g. 'Driving Licence (DL)', 'Vehicle Insurance')
    into canonical DocumentType enum values.
    """
    cleaned = raw_type.strip().upper()
    
    if "LICENCE" in cleaned or "LICENSE" in cleaned or "DL" in cleaned:
        return DocumentType.DRIVING_LICENCE
    if "INSURANCE" in cleaned:
        return DocumentType.INSURANCE
    if "FITNESS" in cleaned or "FC" in cleaned:
        return DocumentType.FITNESS
    if "PUC" in cleaned or "POLLUTION" in cleaned:
        return DocumentType.PUC
    if "PERMIT" in cleaned:
        return DocumentType.PERMIT
    if "TAX" in cleaned:
        return DocumentType.TAX_RECEIPT
    if "BADGE" in cleaned:
        return DocumentType.BADGE
    if "RC" in cleaned or "REGISTRATION" in cleaned:
        return DocumentType.RC
        
    for dt in DocumentType:
        if dt.value == cleaned:
            return dt
            
    return DocumentType.OTHER_VEHICLE


class VehicleDocument(BaseModel):
    """
    Domain model representing an authenticated driver's vehicle or personal document.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    document_id: str = Field(..., description="Unique document ID (e.g. DOC_...)")
    driver_id: str = Field(..., description="Driver identifier")
    vehicle_id: Optional[str] = Field(default=None, description="Vehicle ID (nullable for driver personal docs)")
    document_type: DocumentType = Field(..., description="Canonical document type")
    document_number: Optional[str] = Field(default=None, description="Policy, licence, or registration number")
    issuing_authority: Optional[str] = Field(default=None, description="e.g. RTO Chennai East, ICICI Lombard")
    issue_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    expiry_date: Optional[str] = Field(default=None, description="YYYY-MM-DD (nullable for non-expiring docs)")
    file_reference: Optional[str] = Field(default=None, description="Path or key in private storage")
    file_type: Optional[str] = Field(default=None, description="pdf, png, jpg, jpeg")
    file_size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    upload_timestamp: datetime.datetime = Field(default_factory=now_utc)
    verification_status: VerificationStatus = Field(default=VerificationStatus.UNVERIFIED)
    notes: Optional[str] = Field(default="", description="Optional driver or admin notes")
    is_active: bool = Field(default=True, description="True if current, False if superseded or removed")
    superseded_by: Optional[str] = Field(default=None, description="document_id of newer renewed document")
    created_at: datetime.datetime = Field(default_factory=now_utc)
    updated_at: datetime.datetime = Field(default_factory=now_utc)

    @field_validator("document_type", mode="before")
    @classmethod
    def validate_doc_type(cls, v: Any) -> DocumentType:
        if isinstance(v, DocumentType):
            return v
        if isinstance(v, str):
            return normalize_document_type(v)
        raise ValueError(f"Invalid document type format: {v}")

    def calculate_expiry_status(self, reference_date: Optional[str] = None) -> Tuple[ExpiryStatus, Optional[int]]:
        """
        Calculates expiry status and days remaining relative to reference_date (defaults to today in IST).
        Returns: (ExpiryStatus, days_remaining)
        """
        if not self.expiry_date:
            return ExpiryStatus.UNKNOWN, None

        ref_str = reference_date or today_ist()
        try:
            exp = datetime.date.fromisoformat(self.expiry_date)
            ref = datetime.date.fromisoformat(ref_str)
        except ValueError:
            return ExpiryStatus.UNKNOWN, None

        days_left = (exp - ref).days

        if days_left < 0:
            return ExpiryStatus.EXPIRED, days_left
        elif days_left <= 30:
            return ExpiryStatus.EXPIRING_SOON, days_left
        else:
            return ExpiryStatus.ACTIVE, days_left
