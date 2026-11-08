"""
Unit Tests for LocalStorageAdapter.
Verifies magic-byte sniffing, size bounds, path traversal protection, and file retrieval.
"""

import os
import shutil
import tempfile
import pytest

from app.utils.storage import LocalStorageAdapter


@pytest.fixture
def temp_storage_dir():
    d = tempfile.mkdtemp(prefix="t2t_test_storage_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_valid_pdf_storage(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    fake_pdf = b"%PDF-1.4\n%test pdf content\n%%EOF"

    ref, size, mime = adapter.save_file(fake_pdf, "insurance.pdf")
    assert ref.startswith("doc_")
    assert ref.endswith(".pdf")
    assert size == len(fake_pdf)
    assert mime == "application/pdf"

    retrieved, ret_mime = adapter.get_file(ref)
    assert retrieved == fake_pdf
    assert ret_mime == "application/pdf"


def test_valid_image_storage(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    fake_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF"

    png_ref, _, png_mime = adapter.save_file(fake_png, "rc.png")
    assert png_mime == "image/png"

    jpg_ref, _, jpg_mime = adapter.save_file(fake_jpg, "license.jpeg")
    assert jpg_mime == "image/jpeg"


def test_unsupported_format_rejected(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    with pytest.raises(ValueError, match="Unsupported file format"):
        adapter.save_file(b"echo evil", "malware.exe")


def test_magic_byte_mismatch_rejected(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    # Plain text file disguised as .pdf
    fake_pdf = b"Hello, this is just plain text, not a real PDF"
    with pytest.raises(ValueError, match="File content does not match"):
        adapter.save_file(fake_pdf, "fake.pdf")


def test_oversized_file_rejected(temp_storage_dir):
    # Max size 1 MB
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=1)
    huge_data = b"%PDF" + (b"0" * (1024 * 1024 + 50))
    with pytest.raises(ValueError, match="File exceeds maximum allowed size"):
        adapter.save_file(huge_data, "huge.pdf")


def test_path_traversal_prevention(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    with pytest.raises(PermissionError, match="Invalid file path traversal"):
        adapter.get_file("../../../etc/passwd")


def test_file_deletion(temp_storage_dir):
    adapter = LocalStorageAdapter(base_directory=temp_storage_dir, max_size_mb=2)
    fake_pdf = b"%PDF-1.4\nvalid"
    ref, _, _ = adapter.save_file(fake_pdf, "delete_me.pdf")

    assert adapter.delete_file(ref) is True
    with pytest.raises(FileNotFoundError):
        adapter.get_file(ref)
