"""
Unit tests for AdaptiveAudioPreprocessor in T2T DRIVE Noise Intelligence Engine.
Tests IIR high-pass filtering (sub-120Hz suppression), peak-safe normalization,
silence trimming, and safety fallback.
"""

import io
import math
import struct
import wave
import pytest
from app.voice.noise.adaptive_preprocessor import AdaptiveAudioPreprocessor
from app.voice.noise.noise_classifier import NoiseClassification, NoiseType
from app.voice.noise.vad import VADResult, SpeechSegment
from app.voice.noise.audio_metrics import AudioMetricsCalculator


def make_tone(freq: float, duration: float = 1.0, amplitude: int = 5000, sample_rate: int = 16000) -> bytes:
    bio = io.BytesIO()
    num_samples = int(sample_rate * duration)
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = []
        for i in range(num_samples):
            val = int(math.sin(2 * math.pi * freq * i / sample_rate) * amplitude)
            frames.append(struct.pack("<h", val))
        wf.writeframes(b"".join(frames))
    return bio.getvalue()


def test_high_pass_filter_attenuates_low_frequency():
    preprocessor = AdaptiveAudioPreprocessor(highpass_cutoff_hz=120.0)
    # 50 Hz low rumble
    low_freq_wav = make_tone(50.0, duration=1.0, amplitude=10000)
    classification = NoiseClassification(
        primary_category=NoiseType.ENGINE_NOISE,
        secondary_categories=[],
        confidence=0.85,
        supporting_metrics={},
        is_reliable=True,
        suggested_strategy="HIGH_PASS_FILTER"
    )

    res = preprocessor.process(low_freq_wav, classification=classification)

    assert "HIGH_PASS_FILTER_120HZ" in res.applied_transformations
    calc = AudioMetricsCalculator()
    orig_m = calc.calculate_from_bytes(low_freq_wav)
    proc_m = calc.calculate_from_bytes(res.processed_audio_bytes)
    assert proc_m.rms_energy < orig_m.rms_energy * 0.65  # Substantial attenuation


def test_peak_safe_normalization():
    preprocessor = AdaptiveAudioPreprocessor()
    # Quiet speech tone (-36 dBFS, amp ~ 500)
    quiet_wav = make_tone(440.0, duration=1.0, amplitude=500)
    classification = NoiseClassification(
        primary_category=NoiseType.LOW_VOLUME,
        secondary_categories=[],
        confidence=0.80,
        supporting_metrics={},
        is_reliable=True,
        suggested_strategy="BOOST_GAIN"
    )

    res = preprocessor.process(quiet_wav, classification=classification)

    assert any("PEAK_SAFE_NORMALIZATION" in t for t in res.applied_transformations)
    calc = AudioMetricsCalculator()
    proc_m = calc.calculate_from_bytes(res.processed_audio_bytes)
    assert proc_m.rms_energy > 1200.0  # Boosted safely
    assert proc_m.clipping_percentage == 0.0  # Zero clipping introduced


def test_silence_trimming():
    preprocessor = AdaptiveAudioPreprocessor()
    # 2.0s audio with speech only between 0.6s and 1.4s
    wav_bytes = make_tone(440.0, duration=2.0, amplitude=8000)
    vad_res = VADResult(
        has_speech=True,
        total_duration_seconds=2.0,
        speech_duration_seconds=0.8,
        silence_duration_seconds=1.2,
        speech_percentage=40.0,
        leading_silence_seconds=0.6,
        trailing_silence_seconds=0.6,
        max_pause_seconds=0.0,
        num_speech_segments=1,
        speech_segments=[SpeechSegment(start_seconds=0.6, end_seconds=1.4, duration_seconds=0.8)],
        is_reliable=True,
        confidence=0.9
    )
    classification = NoiseClassification(
        primary_category=NoiseType.CLEAN,
        secondary_categories=[],
        confidence=0.9,
        supporting_metrics={},
        is_reliable=True,
        suggested_strategy="PROCEED_AS_IS"
    )

    res = preprocessor.process(wav_bytes, classification=classification, vad_result=vad_res)

    assert any("SILENCE_TRIM" in t for t in res.applied_transformations)
    calc = AudioMetricsCalculator()
    proc_m = calc.calculate_from_bytes(res.processed_audio_bytes)
    # Output should be trimmed with margin: ~0.8 + 2*0.1 = ~1.0s, well below original 2.0s
    assert proc_m.duration_seconds < 1.3
