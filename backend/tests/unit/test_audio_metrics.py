"""
Unit tests for AudioMetricsCalculator in T2T DRIVE Noise Intelligence Engine.
Tests acoustic property calculation: RMS, peak dBFS, clipping, silence, ZCR, noise floor.
"""

import io
import math
import struct
import wave
import pytest
from app.voice.noise.audio_metrics import AudioMetricsCalculator, AudioMetrics


def create_test_wav(
    duration: float = 1.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: int = 8000,
    channels: int = 1,
    add_clipping: bool = False
) -> bytes:
    """Helper creating raw WAV audio bytes in memory."""
    bio = io.BytesIO()
    num_samples = int(sample_rate * duration)
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        raw_samples = []
        for i in range(num_samples):
            if amplitude == 0:
                val = 0
            else:
                val = int(math.sin(2 * math.pi * frequency * i / sample_rate) * amplitude)
                if add_clipping and abs(val) > 7500:
                    val = 32767 if val > 0 else -32768
                val = max(-32768, min(32767, val))
            raw_samples.append(struct.pack("<h", val))
            if channels == 2:
                raw_samples.append(struct.pack("<h", val))
        wf.writeframes(b"".join(raw_samples))
    return bio.getvalue()


def test_audio_metrics_standard_sine_wave():
    calc = AudioMetricsCalculator()
    wav_bytes = create_test_wav(duration=1.5, sample_rate=16000, frequency=440.0, amplitude=16384)
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")

    assert metrics.duration_seconds == 1.5
    assert metrics.sample_rate == 16000
    assert metrics.channels == 1
    assert metrics.sample_width == 2
    assert metrics.total_samples == 24000
    assert metrics.peak_amplitude == 16384
    # Peak dBFS for 16384 / 32768 is ~ -6.02 dBFS
    assert -6.5 < metrics.peak_dbfs < -5.5
    # RMS for sine with peak 16384 is ~ 11585, dBFS is ~ -9.03 dBFS
    assert -9.5 < metrics.rms_dbfs < -8.5
    assert metrics.clipping_percentage == 0.0
    assert metrics.silence_percentage == 0.0
    # 440 Hz at 16000 SR has ~880 crossings/sec -> ZCR ~ 0.055
    assert 0.04 < metrics.zero_crossing_rate < 0.07


def test_audio_metrics_silence():
    calc = AudioMetricsCalculator()
    wav_bytes = create_test_wav(duration=1.0, sample_rate=16000, amplitude=0)
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")

    assert metrics.duration_seconds == 1.0
    assert metrics.peak_amplitude == 0
    assert metrics.rms_energy == 0.0
    assert metrics.rms_dbfs <= -90.0
    assert metrics.silence_percentage == 100.0
    assert metrics.clipping_percentage == 0.0


def test_audio_metrics_clipping_detection():
    calc = AudioMetricsCalculator()
    wav_bytes = create_test_wav(duration=1.0, sample_rate=16000, amplitude=32767, add_clipping=True)
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")

    assert metrics.clipping_percentage > 5.0
    assert metrics.peak_amplitude in (32767, 32768)
    assert metrics.peak_dbfs >= -0.1


def test_audio_metrics_empty_bytes():
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(b"", audio_format="wav")

    assert metrics.duration_seconds == 0.0
    assert metrics.sample_rate == 16000
    assert metrics.channels == 1
    assert metrics.rms_dbfs <= -90.0


def test_audio_metrics_to_dict():
    calc = AudioMetricsCalculator()
    wav_bytes = create_test_wav(duration=0.5, sample_rate=16000, amplitude=5000)
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")
    d = metrics.to_dict()

    assert "duration_seconds" in d
    assert "rms_dbfs" in d
    assert "estimated_noise_floor_dbfs" in d
    assert "clipping_percentage" in d
    assert "zero_crossing_rate" in d
