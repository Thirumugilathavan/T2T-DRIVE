"""
Unit tests for Audio Validator in T2T DRIVE Voice Pipeline.
Tests size limits, format validation, magic byte detection,
filename sanitization, and temporary file cleanup.
"""

import os
import pytest
from app.voice.audio_validator import AudioValidator, ALLOWED_EXTENSIONS


def test_validator_detects_empty_file():
    validator = AudioValidator(max_upload_mb=5)
    res = validator.validate_bytes(b"")
    assert not res.is_valid
    assert "empty" in res.error.lower()
    assert res.file_size_bytes == 0


def test_validator_rejects_oversized_file():
    validator = AudioValidator(max_upload_mb=1)  # 1MB limit
    oversized_data = b"RIFF" + b"\x00" * (1024 * 1024 + 100)
    res = validator.validate_bytes(oversized_data)
    assert not res.is_valid
    assert "exceeds maximum size" in res.error.lower()


def test_validator_detects_wav_magic_bytes():
    validator = AudioValidator()
    # RIFF....WAVE header
    wav_header = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    res = validator.validate_bytes(wav_header, client_filename="test.wav")
    assert res.is_valid
    assert res.format == "wav"
    assert res.mime_type == "audio/wav"


def test_validator_detects_mp3_and_ogg_and_webm():
    validator = AudioValidator()

    # MP3 with ID3 header
    mp3_data = b"ID3\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    res_mp3 = validator.validate_bytes(mp3_data, client_filename="voice.mp3")
    assert res_mp3.is_valid
    assert res_mp3.format == "mp3"

    # OGG header
    ogg_data = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    res_ogg = validator.validate_bytes(ogg_data, client_filename="voice.ogg")
    assert res_ogg.is_valid
    assert res_ogg.format == "ogg"

    # WebM header (\x1a\x45\xdf\xa3)
    webm_data = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01"
    res_webm = validator.validate_bytes(webm_data, client_filename="voice.webm")
    assert res_webm.is_valid
    assert res_webm.format == "webm"


def test_validator_rejects_unsupported_format():
    validator = AudioValidator()
    # Plain text or executable file
    bad_data = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
    res = validator.validate_bytes(bad_data, client_filename="malicious.exe")
    assert not res.is_valid
    assert "unsupported audio format" in res.error.lower()


def test_safe_temp_file_cleanup():
    validator = AudioValidator()
    wav_header = b"RIFF\x24\x00\x00\x00WAVE"

    created_path = None
    with validator.create_safe_temp_file(wav_header, ext="wav") as temp_path:
        created_path = temp_path
        assert os.path.exists(temp_path)
        assert os.path.isfile(temp_path)
        with open(temp_path, "rb") as f:
            assert f.read() == wav_header

    # File MUST be deleted after exiting context manager
    assert not os.path.exists(created_path)


def test_safe_filename_generation():
    validator = AudioValidator()
    fname1 = validator.generate_safe_filename("wav")
    fname2 = validator.generate_safe_filename("..//..//etc//passwd.mp3")
    assert fname1.startswith("t2t_voice_")
    assert fname1.endswith(".wav")
    assert "passwd" not in fname2
    assert fname2.endswith(".mp3")
