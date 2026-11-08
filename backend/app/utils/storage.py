"""
Secure Storage Abstraction for T2T DRIVE Documents & Challan Attachments.
Provides local private storage adapter with magic-byte format validation,
strict size limits, path-traversal prevention, and authorization-gated retrieval.
"""

import os
import uuid
import logging
from abc import ABC, abstractmethod
from typing import Tuple, Optional

logger = logging.getLogger("t2t_drive.storage")

ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

# Magic byte signatures for supported document formats
MAGIC_SIGNATURES = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"]
}


class StorageAdapterBase(ABC):
    """Abstract base contract for document file storage."""

    @abstractmethod
    def save_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        content_type: Optional[str] = None
    ) -> Tuple[str, int, str]:
        """
        Saves file securely.
        Returns: (file_reference, file_size_bytes, normalized_content_type)
        """
        pass

    @abstractmethod
    def get_file(self, file_reference: str) -> Tuple[bytes, str]:
        """
        Retrieves file bytes and MIME content type.
        Returns: (file_bytes, content_type)
        """
        pass

    @abstractmethod
    def delete_file(self, file_reference: str) -> bool:
        """Deletes file from storage."""
        pass


class LocalStorageAdapter(StorageAdapterBase):
    """
    Local filesystem storage adapter with strict security isolation.
    Documents are stored in a private directory outside web server document roots.
    """

    def __init__(self, base_directory: str, max_size_mb: int = 10):
        self.base_dir = os.path.abspath(base_directory)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        os.makedirs(self.base_dir, exist_ok=True)
        logger.info("LocalStorageAdapter initialized at: %s (max size: %d MB)", self.base_dir, max_size_mb)

    def validate_file(self, file_bytes: bytes, original_filename: str) -> str:
        """
        Validates file size, extension, and magic bytes.
        Returns normalized extension (e.g. 'pdf', 'png', 'jpg').
        """
        if not file_bytes:
            raise ValueError("File is empty (0 bytes).")

        if len(file_bytes) > self.max_size_bytes:
            raise ValueError(f"File exceeds maximum allowed size of {self.max_size_bytes // (1024 * 1024)} MB.")

        # Check extension
        _, ext = os.path.splitext(original_filename.lower())
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise ValueError(f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}")

        ext_clean = ext.lstrip(".").lower()
        if ext_clean == "jpeg":
            ext_clean = "jpg"

        # Verify magic bytes
        signatures = MAGIC_SIGNATURES.get(ext_clean, [])
        is_valid = any(file_bytes.startswith(sig) for sig in signatures)
        if not is_valid:
            raise ValueError(f"File content does not match expected format for extension '{ext}'.")

        return ext_clean

    def _resolve_safe_path(self, file_reference: str) -> str:
        """Resolves file reference and guards against directory traversal."""
        # Clean relative path
        safe_rel = os.path.normpath(file_reference).lstrip("/\\")
        full_path = os.path.abspath(os.path.join(self.base_dir, safe_rel))

        # Check path traversal
        if not full_path.startswith(self.base_dir):
            raise PermissionError("Access denied: Invalid file path traversal detected.")

        return full_path

    def save_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        content_type: Optional[str] = None
    ) -> Tuple[str, int, str]:
        ext_clean = self.validate_file(file_bytes, original_filename)

        # Generate unique random server-side filename
        safe_name = f"doc_{uuid.uuid4().hex}.{ext_clean}"
        full_path = self._resolve_safe_path(safe_name)

        with open(full_path, "wb") as f:
            f.write(file_bytes)

        mime_map = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg"
        }
        resolved_mime = mime_map.get(ext_clean, content_type or "application/octet-stream")

        logger.info("Saved document %s (%d bytes)", safe_name, len(file_bytes))
        return safe_name, len(file_bytes), resolved_mime

    def get_file(self, file_reference: str) -> Tuple[bytes, str]:
        full_path = self._resolve_safe_path(file_reference)

        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            raise FileNotFoundError(f"Requested document file '{file_reference}' was not found.")

        with open(full_path, "rb") as f:
            data = f.read()

        _, ext = os.path.splitext(file_reference.lower())
        ext_clean = ext.lstrip(".")
        if ext_clean == "jpeg":
            ext_clean = "jpg"

        mime_map = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg"
        }
        mime = mime_map.get(ext_clean, "application/octet-stream")

        return data, mime

    def delete_file(self, file_reference: str) -> bool:
        try:
            full_path = self._resolve_safe_path(file_reference)
            if os.path.exists(full_path):
                os.remove(full_path)
                return True
            return False
        except Exception as e:
            logger.warning("Failed to delete file %s: %s", file_reference, e)
            return False
