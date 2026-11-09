"""
Unit tests for NoiseClassifier in T2T DRIVE Noise Intelligence Engine.
Tests heuristic classification of CLEAN, ENGINE_NOISE, TRAFFIC_NOISE, HONKING,
CLIPPING, LOW_VOLUME, and SILENCE.
"""

import pytest
from app.voice.noise.audio_metrics import AudioMetrics
from app.voice.noise.snr_estimator import SNREstimate, SNRQuality
from app.voice.noise.noise_classifier import NoiseClassifier, NoiseType


def make_metrics(
    rms_dbfs: float = -20.0,
    peak_dbfs: float = -6.0,
    clipping_pct: float = 0.0,
    silence_pct: float = 0.0,
    zcr: float = 0.09,
    noise_floor: float = -50.0,
    crest_factor: float = 14.0
) -> AudioMetrics:
    return AudioMetrics(
        duration_seconds=2.0,
        sample_rate=16000,
        channels=1,
        sample_width=2,
        total_samples=32000,
        rms_energy=3000.0,
        rms_dbfs=rms_dbfs,
        peak_amplitude=16000,
        peak_dbfs=peak_dbfs,
        clipping_samples=int(32000 * (clipping_pct / 100.0)),
        clipping_percentage=clipping_pct,
        zero_crossing_rate=zcr,
        estimated_noise_floor_dbfs=noise_floor,
        silence_percentage=silence_pct,
        estimated_speech_percentage=100.0 - silence_pct,
        dynamic_range_db=30.0,
        crest_factor_db=crest_factor,
        is_pcm_analyzed=True,
        format="wav"
    )


def test_classify_silence():
    classifier = NoiseClassifier()
    m = make_metrics(rms_dbfs=-60.0, peak_dbfs=-55.0, silence_pct=95.0)
    res = classifier.classify(m)

    assert res.primary_category == NoiseType.SILENCE
    assert res.confidence >= 0.90
    assert "SPEAK_LOUDER" in res.suggested_strategy or "REPEAT" in res.suggested_strategy


def test_classify_clipping():
    classifier = NoiseClassifier()
    m = make_metrics(clipping_pct=4.5, peak_dbfs=0.0)
    res = classifier.classify(m)

    assert res.primary_category == NoiseType.CLIPPING
    assert res.confidence >= 0.85
    assert "ATTENUATE" in res.suggested_strategy


def test_classify_low_volume():
    classifier = NoiseClassifier()
    m = make_metrics(rms_dbfs=-40.0, peak_dbfs=-28.0)
    res = classifier.classify(m)

    assert res.primary_category == NoiseType.LOW_VOLUME
    assert "NORMALIZE" in res.suggested_strategy or "CLOSER" in res.suggested_strategy


def test_classify_engine_noise():
    classifier = NoiseClassifier()
    m = make_metrics(zcr=0.05, noise_floor=-38.0, crest_factor=10.0)
    snr = SNREstimate(
        snr_db=8.0,
        quality=SNRQuality.POOR,
        speech_level_dbfs=-20.0,
        noise_floor_dbfs=-28.0,
        estimation_method="minimum_statistics",
        is_reliable=True
    )
    res = classifier.classify(m, snr_est=snr)

    assert res.primary_category == NoiseType.ENGINE_NOISE
    assert "HIGH_PASS_FILTER" in res.suggested_strategy


def test_classify_honking():
    classifier = NoiseClassifier()
    m = make_metrics(crest_factor=16.0, zcr=0.18, clipping_pct=0.0)
    res = classifier.classify(m)

    assert res.primary_category == NoiseType.HONKING
    assert "REQUEST_REPEAT" in res.suggested_strategy


def test_classify_clean():
    classifier = NoiseClassifier()
    m = make_metrics(rms_dbfs=-18.0, peak_dbfs=-5.0, zcr=0.09, clipping_pct=0.0, noise_floor=-55.0)
    snr = SNREstimate(
        snr_db=22.0,
        quality=SNRQuality.GOOD,
        speech_level_dbfs=-18.0,
        noise_floor_dbfs=-40.0,
        estimation_method="minimum_statistics",
        is_reliable=True
    )
    res = classifier.classify(m, snr_est=snr)

    assert res.primary_category == NoiseType.CLEAN
    assert res.confidence >= 0.85
    assert res.suggested_strategy == "PROCEED_AS_IS"
