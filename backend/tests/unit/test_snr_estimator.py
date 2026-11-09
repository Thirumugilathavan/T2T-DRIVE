"""
Unit tests for SNREstimator in T2T DRIVE Noise Intelligence Engine.
Tests minimum-statistics SNR estimation, quality classification, and reliability flagging.
"""

import io
import math
import struct
import wave
import pytest
from app.voice.noise.audio_metrics import AudioMetricsCalculator
from app.voice.noise.snr_estimator import SNREstimator, SNRQuality


def make_composite_wav(
    signal_amp: int = 10000,
    noise_amp: int = 500,
    duration: float = 2.0,
    sample_rate: int = 16000
) -> bytes:
    """Creates a WAV with alternating active signal bursts and background noise."""
    bio = io.BytesIO()
    num_samples = int(sample_rate * duration)
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = []
        for i in range(num_samples):
            t = i / sample_rate
            # 0.5s pause, 1.0s signal, 0.5s pause
            is_active = 0.5 <= t <= 1.5
            noise = int(math.sin(2 * math.pi * 80 * i / sample_rate) * noise_amp)
            sig = int(math.sin(2 * math.pi * 500 * i / sample_rate) * signal_amp) if is_active else 0
            val = max(-32768, min(32767, sig + noise))
            frames.append(struct.pack("<h", val))
        wf.writeframes(b"".join(frames))
    return bio.getvalue()


def test_snr_clean_audio():
    # Signal 12000, Noise 50 -> Expected SNR > 20 dB
    wav_bytes = make_composite_wav(signal_amp=12000, noise_amp=50, duration=2.0)
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")
    samples, _, _ = calc.unpack_samples(wav_bytes)

    estimator = SNREstimator()
    snr_est = estimator.estimate(metrics, samples=samples)

    assert snr_est.snr_db is not None
    assert snr_est.snr_db >= 20.0
    assert snr_est.quality == SNRQuality.GOOD
    assert snr_est.is_reliable is True


def test_snr_moderate_noise():
    # Signal 5000, Noise 1200 -> Expected SNR ~ 10-14 dB
    wav_bytes = make_composite_wav(signal_amp=5000, noise_amp=1200, duration=2.0)
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")
    samples, _, _ = calc.unpack_samples(wav_bytes)

    estimator = SNREstimator()
    snr_est = estimator.estimate(metrics, samples=samples)

    assert snr_est.snr_db is not None
    assert 8.0 <= snr_est.snr_db <= 18.0
    assert snr_est.quality in (SNRQuality.MODERATE, SNRQuality.GOOD)


def test_snr_poor_noise():
    # Signal 2000, Noise 1600 -> Expected SNR < 8 dB
    wav_bytes = make_composite_wav(signal_amp=2000, noise_amp=1600, duration=2.0)
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")
    samples, _, _ = calc.unpack_samples(wav_bytes)

    estimator = SNREstimator()
    snr_est = estimator.estimate(metrics, samples=samples)

    assert snr_est.snr_db is not None
    assert snr_est.snr_db < 10.0
    assert snr_est.quality in (SNRQuality.POOR, SNRQuality.VERY_POOR)


def test_snr_very_short_audio_unreliable():
    # Audio under 0.4s should be marked unreliable
    wav_bytes = make_composite_wav(signal_amp=5000, noise_amp=200, duration=0.25)
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(wav_bytes, audio_format="wav")

    estimator = SNREstimator()
    snr_est = estimator.estimate(metrics)

    assert snr_est.is_reliable is False
    assert "under 400ms" in snr_est.unreliability_reason


def test_snr_pure_silence():
    calc = AudioMetricsCalculator()
    metrics = calc.calculate_from_bytes(b"", audio_format="wav")

    estimator = SNREstimator()
    snr_est = estimator.estimate(metrics)

    assert snr_est.quality == SNRQuality.UNKNOWN
    assert snr_est.is_reliable is False
