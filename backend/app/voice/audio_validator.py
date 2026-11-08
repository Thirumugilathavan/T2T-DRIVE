"""
Audio Validator for T2T DRIVE Voice Pipeline.
Enforces security, maximum upload sizes, mime type verification,
magic byte headers, and safe temporary file lifecycle management.
"""

import os
import secrets
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
from contextlib import contextmanager

from app.voice.schemas import AudioValidationResult

logger = logging.getLogger("t2t_drive.audio_validator")

# Supported audio extensions & mime types
ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "webm", "m4a", "aac"}

MIME_TYPE_MAP = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
}

# Magic byte signatures for audio formats
MAGIC_SIGNATURES = {
    "wav": [(0, b"RIFF"), (8, b"WAVE")],
    "ogg": [(0, b"OggS")],
    "webm": [(0, b"\x1a\x45\xdf\xa3")],  # EBML header
    "mp3_id3": [(0, b"ID3")],
    "mp3_sync": [(0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2")],
    "m4a": [(4, b"ftyp")],
    "aac_adts": [(0, b"\xff\xf1"), (0, b"\xff\xf9")],
}


class AudioValidationError(Exception):
    """Raised when an uploaded audio file violates security or format constraints."""
    pass


class AudioValidator:
    """
    Validates uploaded audio files for security, format, size, and header integrity.
    """

    def __init__(self, max_upload_mb: int = 10, temp_dir: Optional[str] = None):
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self.temp_dir = temp_dir or tempfile.gettempdir()
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

    def validate_bytes(self, data: bytes, client_filename: Optional[str] = None) -> AudioValidationResult:
        """
        Validates raw audio bytes directly in memory.
        """
        size = len(data)

        # 1. Size checks
        if size == 0:
            return AudioValidationResult(
                is_valid=False,
                format="unknown",
                mime_type="application/octet-stream",
                file_size_bytes=0,
                error="Audio file is empty (0 bytes)."
            )

        if size > self.max_upload_bytes:
            return AudioValidationResult(
                is_valid=False,
                format="unknown",
                mime_type="application/octet-stream",
                file_size_bytes=size,
                error=f"Audio file exceeds maximum size of {self.max_upload_bytes // (1024 * 1024)}MB."
            )

        # 2. Extract extension hint from client filename if provided
        ext_hint = None
        if client_filename and "." in client_filename:
            ext_hint = client_filename.rsplit(".", 1)[-1].lower().strip()

        # 3. Detect format from magic bytes
        detected_format = self._detect_format_from_magic_bytes(data)

        # Fallback to extension hint if magic byte check is inconclusive but matches standard audio
        if not detected_format and ext_hint in ALLOWED_EXTENSIONS:
            detected_format = ext_hint

        if not detected_format or detected_format not in ALLOWED_EXTENSIONS:
            return AudioValidationResult(
                is_valid=False,
                format=detected_format or "unknown",
                mime_type="application/octet-stream",
                file_size_bytes=size,
                error=f"Unsupported audio format. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            )

        mime_type = MIME_TYPE_MAP.get(detected_format, "application/octet-stream")

        return AudioValidationResult(
            is_valid=True,
            format=detected_format,
            mime_type=mime_type,
            file_size_bytes=size,
            error=None
        )

    def _detect_format_from_magic_bytes(self, header: bytes) -> Optional[str]:
        """Inspects binary header for known audio signatures."""
        if len(header) < 12:
            return None

        # Check WAV (RIFF + WAVE)
        if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return "wav"

        # Check OGG
        if header.startswith(b"OggS"):
            return "ogg"

        # Check WebM / Matroska
        if header.startswith(b"\x1a\x45\xdf\xa3"):
            return "webm"

        # Check MP3 with ID3 tag
        if header.startswith(b"ID3"):
            return "mp3"

        # Check MP3 raw frame sync
        if header.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "mp3"

        # Check M4A (ftyp at offset 4)
        if len(header) >= 8 and header[4:8] == b"ftyp":
            return "m4a"

        # Check AAC ADTS
        if header.startswith((b"\xff\xf1", b"\xff\xf9")):
            return "aac"

        return None

    def generate_safe_filename(self, ext: str) -> str:
        """Generates a secure server-side filename with no client-controlled path components."""
        clean_ext = ext.rsplit(".", 1)[-1].lower().strip()
        if clean_ext not in ALLOWED_EXTENSIONS:
            clean_ext = "wav"
        return f"t2t_voice_{secrets.token_hex(12)}.{clean_ext}"

    @contextmanager
    def create_safe_temp_file(self, data: bytes, ext: str = "wav"):
        """
        Context manager that writes audio bytes to a secure temporary file
        and guarantees cleanup upon exit, even if exceptions occur.
        """
        filename = self.generate_safe_filename(ext)
        filepath = os.path.join(self.temp_dir, filename)

        try:
            with open(filepath, "wb") as f:
                f.write(data)
            yield filepath
        finally:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError as err:
                    logger.warning("Failed to remove temporary audio file %s: %s", filepath, err)
