"""
Pydantic Request and Response Schemas for Vehicle & Driver Documents.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
import datetime

from app.models.vehicle_document import DocumentType, ExpiryStatus, VerificationStatus


class DocumentCreateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_type: str = Field(..., description="Document type name (e.g. 'Driving Licence', 'Insurance', 'RC')")
    vehicle_id: Optional[str] = Field(default=None, description="Vehicle ID (optional for personal docs like DL)")
    document_number: Optional[str] = Field(default=None, description="Document identifier/policy number")
    issuing_authority: Optional[str] = Field(default=None, description="Issuing body/authority")
    issue_date: Optional[str] = Field(default=None, description="Issue date YYYY-MM-DD")
    expiry_date: Optional[str] = Field(default=None, description="Expiry date YYYY-MM-DD")
    notes: Optional[str] = Field(default="", description="Optional remarks")


class DocumentUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None


class DocumentResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    driver_id: str
    vehicle_id: Optional[str]
    document_type: str
    document_number_masked: Optional[str]
    issuing_authority: Optional[str]
    issue_date: Optional[str]
    expiry_date: Optional[str]
    days_left: Optional[int]
    expiry_status: str
    verification_status: str
    has_file: bool
    file_type: Optional[str]
    is_active: bool
    notes: Optional[str]
    created_at: str
    updated_at: str
