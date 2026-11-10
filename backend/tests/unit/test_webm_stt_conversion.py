"""
Unit and integration tests for WebM audio conversion to genuine 16kHz Mono WAV
and Prisma STT ingestion without RIFF header decoding failure.
"""

import os
import io
import wave
import struct
import tempfile
import subprocess
import pytest
from unittest.mock import MagicMock, patch

from app.voice.audio_preprocessor import AudioPreprocessor
from app.voice.audio_validator import AudioValidator
from app.voice.voice_service import VoiceService
from app.voice.prisma_adapter import MockPrismaAdapter, PrismaAdapter
from app.voice.schemas import STTResponse


def _create_synthetic_wav(duration_s=1.0, sample_rate=16000, freq=440.0) -> bytes:
    """Generates a valid 16kHz Mono 16-bit PCM WAV in memory."""
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        import math
        num_frames = int(duration_s * sample_rate)
        data = bytearray()
        for i in range(num_frames):
            val = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
            data.extend(struct.pack("<h", val))
        wf.writeframes(data)
    return bio.getvalue()


def _create_synthetic_webm_from_wav(wav_bytes: bytes) -> bytes:
    """Uses FFmpeg to produce a genuine WebM Opus audio file from WAV."""
    exe = AudioPreprocessor.get_ffmpeg_executable()
    assert exe is not None, "FFmpeg executable is required for test"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_in:
        f_in.write(wav_bytes)
        in_path = f_in.name

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f_out:
        out_path = f_out.name

    try:
        subprocess.run(
            [exe, "-y", "-i", in_path, "-c:a", "libopus", out_path],
            check=True,
            capture_output=True
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


def test_ffmpeg_executable_available():
    """Verify that FFmpeg binary is found on system or via imageio-ffmpeg."""
    exe = AudioPreprocessor.get_ffmpeg_executable()
    assert exe is not None
    assert os.path.exists(exe)


def test_empty_audio_rejection():
    """Verify empty audio raises clear ValueError."""
    with pytest.raises(ValueError, match="Audio data is empty"):
        AudioPreprocessor.convert_to_16k_mono_wav(b"")


def test_corrupt_audio_rejection():
    """Verify invalid/corrupt audio raises clear ValueError."""
    with pytest.raises(ValueError, match="FFmpeg audio conversion failed"):
        AudioPreprocessor.convert_to_16k_mono_wav(b"not-real-audio-header-garbage", input_format="webm")


def test_webm_to_16k_mono_wav_conversion():
    """Verify converting a WebM Opus audio produces genuine 16kHz mono WAV with valid RIFF header."""
    wav_in = _create_synthetic_wav(duration_s=1.0)
    webm_bytes = _create_synthetic_webm_from_wav(wav_in)

    assert webm_bytes[:4] == b"\x1a\x45\xdf\xa3", "Must have EBML/WebM magic bytes"

    # Convert via AudioPreprocessor
    converted_wav = AudioPreprocessor.convert_to_16k_mono_wav(webm_bytes, input_format="webm")

    # Verify RIFF/WAVE header
    assert len(converted_wav) > 44
    assert converted_wav[:4] == b"RIFF"
    assert converted_wav[8:12] == b"WAVE"

    # Verify audio properties using Python standard wave module
    with io.BytesIO(converted_wav) as bio:
        with wave.open(bio, "rb") as wf:
            assert wf.getnchannels() == 1, "Must be mono"
            assert wf.getframerate() == 16000, "Must be 16000 Hz"
            assert wf.getsampwidth() == 2, "Must be 16-bit PCM"


def test_voice_service_transcribes_webm_successfully():
    """Verify VoiceService receives WebM, converts to WAV, and transcribes without decoding errors."""
    wav_in = _create_synthetic_wav(duration_s=1.0)
    webm_bytes = _create_synthetic_webm_from_wav(wav_in)

    mock_prisma = MockPrismaAdapter(default_transcript="வணக்கம் 500 ரூபாய் டீசல்")
    voice_svc = VoiceService(
        prisma_adapter=mock_prisma,
        timbre_adapter=MagicMock(),
        agent_service=MagicMock(),
        validator=AudioValidator(),
        preprocessor=AudioPreprocessor()
    )

    res = voice_svc.transcribe_audio(
        audio_bytes=webm_bytes,
        filename="recording.webm",
        language_hint="ta-IN"
    )

    assert res.processing_status == "SUCCESS"
    assert "டீசல்" in res.transcript


def test_voice_service_rejects_empty_audio_file():
    """Verify empty audio is rejected with clear error."""
    mock_prisma = MockPrismaAdapter()
    voice_svc = VoiceService(
        prisma_adapter=mock_prisma,
        timbre_adapter=MagicMock(),
        agent_service=MagicMock()
    )
    res = voice_svc.transcribe_audio(audio_bytes=b"", filename="empty.webm")
    assert res.processing_status == "ERROR"
    assert "empty" in res.error.lower()


def test_live_gnani_prisma_transcription_from_webm():
    """
    Integration verification: Converts WebM audio to genuine 16kHz mono WAV
    and confirms successful live transcription via Gnani Prisma STT.
    Skipped if GNANI_API_KEY is missing or if external network is unavailable.
    """
    from dotenv import load_dotenv
    load_dotenv("backend/.env")
    api_key = os.getenv("GNANI_API_KEY")
    if not api_key:
        pytest.skip("GNANI_API_KEY not configured; skipping live STT test.")

    from app.voice.timbre_adapter import TimbreAdapter
    from app.voice.prisma_adapter import PrismaAdapter

    # 1. Synthesize clear speech via Timbre TTS
    tts = TimbreAdapter(api_key=api_key)
    try:
        tts_res = tts.synthesize("வணக்கம் 500 ரூபாய் டீசல்", language="ta-IN", voice="Kaveri")
    except Exception as e:
        pytest.skip(f"External network unavailable for Timbre TTS: {e}")

    if not tts_res.audio_bytes:
        if "getaddrinfo failed" in str(tts_res.error or ""):
            pytest.skip("External network unreachable (sandbox mode); skipping live TTS/STT test.")
        assert False, f"TTS synthesis failed: {tts_res.error}"

    # 2. Package into WebM Opus container (replicating browser MediaRecorder)
    webm_bytes = _create_synthetic_webm_from_wav(tts_res.audio_bytes)
    assert webm_bytes[:4] == b"\x1a\x45\xdf\xa3", "Must be genuine WebM"

    # 3. Transcribe through PrismaAdapter (which converts via AudioPreprocessor)
    stt = PrismaAdapter(api_key=api_key)
    converted_wav = AudioPreprocessor.convert_to_16k_mono_wav(webm_bytes, input_format="webm")
    assert converted_wav[:4] == b"RIFF"
    assert converted_wav[8:12] == b"WAVE"

    try:
        res = stt.transcribe(converted_wav, filename="audio.wav", language_hint="ta-IN", mime_type="audio/wav")
    except Exception as e:
        pytest.skip(f"External network unavailable for Prisma STT: {e}")

    if res.processing_status != "SUCCESS" and "getaddrinfo failed" in str(res.error or ""):
        pytest.skip("External network unreachable (sandbox mode); skipping live STT verification.")

    assert res.processing_status == "SUCCESS", f"Prisma failed with: {res.error}"
    assert res.transcript is not None and len(res.transcript.strip()) > 0
    assert res.detected_language in ("ta", "ta-IN", "indic-auto")

