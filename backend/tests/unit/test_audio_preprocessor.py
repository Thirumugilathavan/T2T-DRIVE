"""
Unit tests for Audio Preprocessor in T2T DRIVE Voice Pipeline.
Tests WAV property extraction, duration bounds, silence detection,
and compressed format passthrough.
"""

import io
import wave
import struct
import math
from app.voice.audio_preprocessor import AudioPreprocessor


def make_test_wav(duration: float = 1.0, sample_rate: int = 16000, amplitude: int = 8000) -> bytes:
    """Helper creating raw WAV audio bytes in memory."""
    bio = io.BytesIO()
    num_frames = int(sample_rate * duration)
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = []
        for i in range(num_frames):
            val = int(math.sin(2 * math.pi * 440 * i / sample_rate) * amplitude) if amplitude > 0 else 0
            frames.append(struct.pack("<h", val))
        wf.writeframes(b"".join(frames))
    return bio.getvalue()


def test_preprocessor_extracts_wav_properties():
    preprocessor = AudioPreprocessor(min_duration_seconds=0.2, max_duration_seconds=10.0)
    audio_bytes = make_test_wav(duration=1.5, sample_rate=16000, amplitude=6000)

    res = preprocessor.inspect_and_preprocess(audio_bytes, audio_format="wav")
    assert res["is_processable"]
    assert res["duration_seconds"] == 1.5
    assert res["sample_rate"] == 16000
    assert res["channels"] == 1
    assert not res["is_silent"]


def test_preprocessor_rejects_too_short_audio():
    preprocessor = AudioPreprocessor(min_duration_seconds=0.5)
    audio_bytes = make_test_wav(duration=0.1, sample_rate=16000, amplitude=6000)

    res = preprocessor.inspect_and_preprocess(audio_bytes, audio_format="wav")
    assert not res["is_processable"]
    assert "too short" in res["error"].lower()


def test_preprocessor_rejects_too_long_audio():
    preprocessor = AudioPreprocessor(max_duration_seconds=2.0)
    audio_bytes = make_test_wav(duration=3.0, sample_rate=16000, amplitude=6000)

    res = preprocessor.inspect_and_preprocess(audio_bytes, audio_format="wav")
    assert not res["is_processable"]
    assert "too long" in res["error"].lower()


def test_preprocessor_detects_silent_wav():
    preprocessor = AudioPreprocessor(silence_threshold_rms=50.0)
    # Zero amplitude = complete silence
    silent_bytes = make_test_wav(duration=1.0, sample_rate=16000, amplitude=0)

    res = preprocessor.inspect_and_preprocess(silent_bytes, audio_format="wav")
    assert not res["is_processable"]
    assert res["is_silent"]
    assert "silent" in res["error"].lower()


def test_preprocessor_passes_compressed_format():
    preprocessor = AudioPreprocessor()
    dummy_webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 1000

    res = preprocessor.inspect_and_preprocess(dummy_webm, audio_format="webm")
    assert res["is_processable"]
    assert res["audio_bytes"] == dummy_webm
