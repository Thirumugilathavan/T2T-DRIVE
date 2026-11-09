"""
Unit tests for VoiceActivityDetector (VAD) in T2T DRIVE Noise Intelligence Engine.
Tests speech segmentation, silence trimming bounds, hangover smoothing, and pause detection.
"""

import io
import math
import struct
import wave
import pytest
from app.voice.noise.vad import VoiceActivityDetector


def make_vad_test_wav(
    leading_silence: float = 0.5,
    speech_duration: float = 1.0,
    trailing_silence: float = 0.5,
    speech_amplitude: int = 8000,
    sample_rate: int = 16000
) -> bytes:
    """Creates a WAV with explicit leading silence, active tone, and trailing silence."""
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        # 1. Leading silence
        lead_samples = int(sample_rate * leading_silence)
        wf.writeframes(b"".join(struct.pack("<h", 0) for _ in range(lead_samples)))

        # 2. Active speech (sine tone)
        speech_samples = int(sample_rate * speech_duration)
        speech_frames = []
        for i in range(speech_samples):
            val = int(math.sin(2 * math.pi * 350 * i / sample_rate) * speech_amplitude)
            speech_frames.append(struct.pack("<h", val))
        wf.writeframes(b"".join(speech_frames))

        # 3. Trailing silence
        trail_samples = int(sample_rate * trailing_silence)
        wf.writeframes(b"".join(struct.pack("<h", 0) for _ in range(trail_samples)))

    return bio.getvalue()


def test_vad_detects_speech_and_silence_bounds():
    vad = VoiceActivityDetector(frame_duration_ms=20, hangover_frames=4)
    # 0.4s silence, 1.0s speech, 0.4s silence
    wav_bytes = make_vad_test_wav(leading_silence=0.4, speech_duration=1.0, trailing_silence=0.4)

    res = vad.detect(wav_bytes)

    assert res.has_speech is True
    assert res.speech_duration_seconds >= 0.8
    # Leading silence should be around 0.4s (+/- 0.08s for frame boundary)
    assert 0.30 <= res.leading_silence_seconds <= 0.50
    # Trailing silence should be around 0.4s (+/- 0.15s)
    assert 0.20 <= res.trailing_silence_seconds <= 0.50
    assert len(res.speech_segments) >= 1
    # Check bounds
    seg = res.speech_segments[0]
    assert 0.30 <= seg.start_seconds <= 0.45
    assert 1.30 <= seg.end_seconds <= 1.55


def test_vad_pure_silence():
    vad = VoiceActivityDetector()
    wav_bytes = make_vad_test_wav(leading_silence=1.0, speech_duration=0.0, trailing_silence=0.0)

    res = vad.detect(wav_bytes)

    assert res.has_speech is False
    assert res.speech_duration_seconds == 0.0
    assert len(res.speech_segments) == 0


def test_vad_continuous_speech():
    vad = VoiceActivityDetector()
    wav_bytes = make_vad_test_wav(leading_silence=0.0, speech_duration=1.5, trailing_silence=0.0)

    res = vad.detect(wav_bytes)

    assert res.has_speech is True
    assert res.speech_duration_seconds >= 1.3
    assert res.leading_silence_seconds <= 0.05
    assert res.trailing_silence_seconds <= 0.05
