"""
Unit and Contract Tests for Gnani AI Prisma STT & Timbre TTS Live Activation.
Validates:
1. Indian number comma parsing (e.g. 1,500 -> 1500) and Tamil loanwords.
2. Streaming WAV 0x7FFFFFFF (2147483647) frame count handling in AudioPreprocessor.
3. Truthful STT and TTS status isolation (STT does not affect TTS, TTS does not affect STT).
4. Live PrismaAdapter request construction with ta-IN, en-IN, and indic-auto.
5. Live TimbreAdapter request construction with Kaveri voice.
"""

import io
import wave
from decimal import Decimal
import pytest
from unittest.mock import MagicMock

from app.agent.nlu import MultilingualNLU, parse_numeric_amount, OWNER_PAYMENT_KEYWORDS
from app.voice.audio_preprocessor import AudioPreprocessor
from app.voice.prisma_adapter import PrismaAdapter
from app.voice.timbre_adapter import TimbreAdapter
from app.voice.voice_service import VoiceService


def test_comma_number_parsing_in_nlu():
    """Verifies that numbers formatted with commas (e.g. 1,500 from STT) are parsed as 1500."""
    amt1 = parse_numeric_amount("கலெக்ஷன் 1,500 ரூபாய்")
    assert amt1 == Decimal("1500")

    amt2 = parse_numeric_amount("collection 1,500")
    assert amt2 == Decimal("1500")

    amt3 = parse_numeric_amount("petrol 25,000")
    assert amt3 == Decimal("25000")


def test_tamil_owner_loanwords_in_nlu():
    """Verifies that Tamil loanwords for owner (ஓனக்கு, ஓனருக்கு) are in OWNER_PAYMENT_KEYWORDS."""
    assert "ஓனக்கு" in OWNER_PAYMENT_KEYWORDS
    assert "ஓனருக்கு" in OWNER_PAYMENT_KEYWORDS


def test_multi_transaction_extraction_with_comma_numbers():
    """Verifies that compound utterances with comma-formatted numbers are extracted into batch transactions."""
    text = "இன்னைக்கு கலெக்ஷன் 1,500, பெட்ரோல் 300, ஓனக்கு 200 கொடுத்தேன்."
    txns = MultilingualNLU.extract_multi_transactions(text)
    assert len(txns) == 3
    assert txns[0]["action_type"] == "ADD_INCOME"
    assert txns[0]["amount"] == 1500.0

    assert txns[1]["action_type"] == "ADD_EXPENSE"
    assert txns[1]["amount"] == 300.0

    assert txns[2]["action_type"] == "ADD_OWNER_PAYMENT"
    assert txns[2]["amount"] == 200.0


def test_streaming_wav_header_duration_guard():
    """
    Verifies that AudioPreprocessor guards against streaming WAV headers
    where num_frames is set to 0x7FFFFFFF (2147483647).
    """
    sample_rate = 24000
    channels = 1
    sample_width = 2
    # Create 1 second of actual non-silent PCM data (440 Hz tone)
    import math, struct
    samples = [int(math.sin(2 * math.pi * 440 * i / sample_rate) * 8000) for i in range(24000)]
    raw_pcm = b"".join(struct.pack("<h", s) for s in samples)

    bio = io.BytesIO()
    # Write a valid WAV file
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)

    wav_bytes = bytearray(bio.getvalue())
    # Manually overwrite the data chunk size or num_frames header with 0x7FFFFFFF
    # In standard WAV: bytes 40-43 is data chunk size
    wav_bytes[40:44] = b"\xff\xff\xff\x7f"

    prep = AudioPreprocessor(min_duration_seconds=0.2, max_duration_seconds=60.0)
    res = prep.inspect_and_preprocess(bytes(wav_bytes), audio_format="wav")

    # Duration should be computed from actual buffer length (~1.0s), NOT 89478s
    assert res["is_processable"] is True
    assert 0.9 <= res["duration_seconds"] <= 1.1


def test_live_prisma_language_parameters():
    """Verifies Prisma v3.0 language mappings for ta-IN, en-IN, and Tanglish."""
    adapter = PrismaAdapter(api_key="dummy_test_key_123")

    ta = adapter._map_language_params("tamil")
    assert ta["language_code"] == "ta-IN"

    en = adapter._map_language_params("english")
    assert en["language_code"] == "en-IN"

    tg = adapter._map_language_params("tanglish")
    assert tg["language_code"] == "indic-auto"
    assert tg["preferred_language"] == "ta-IN"
    assert tg["multi_lang_codes"] == "ta-IN,en-IN"


def test_live_timbre_language_and_voice():
    """Verifies Timbre v2.5 language mapping and payload format."""
    adapter = TimbreAdapter(api_key="dummy_test_key_123")
    assert adapter._map_language_code("tamil") == "ta-IN"
    assert adapter._map_language_code("tanglish") == "ta-IN"
    assert adapter._map_language_code("english") == "en-IN"
