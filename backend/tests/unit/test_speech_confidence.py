"""
Unit tests for SpeechConfidenceEvaluator in T2T DRIVE Noise Intelligence Engine.
Tests multidimensional confidence scoring and strict operational directives.
"""

import pytest
from app.voice.noise.speech_confidence import (
    SpeechConfidenceEvaluator,
    ConfidenceDirective,
    MultiDimensionalConfidence
)
from app.voice.noise.noise_classifier import NoiseClassification, NoiseType
from app.voice.noise.snr_estimator import SNREstimate, SNRQuality
from app.voice.noise.vad import VADResult, SpeechSegment


def make_context(
    noise_type: NoiseType = NoiseType.CLEAN,
    snr_db: float = 22.0,
    snr_quality: SNRQuality = SNRQuality.GOOD,
    has_speech: bool = True,
    clipping_pct: float = 0.0
):
    noise_class = NoiseClassification(
        primary_category=noise_type,
        secondary_categories=[],
        confidence=0.90,
        supporting_metrics={"clipping_pct": clipping_pct},
        is_reliable=True,
        suggested_strategy="TEST"
    )
    snr_est = SNREstimate(
        snr_db=snr_db,
        quality=snr_quality,
        speech_level_dbfs=-18.0 if has_speech else None,
        noise_floor_dbfs=-40.0,
        estimation_method="test",
        is_reliable=True
    )
    vad_res = VADResult(
        has_speech=has_speech,
        total_duration_seconds=1.1,
        speech_duration_seconds=0.9 if has_speech else 0.0,
        silence_duration_seconds=0.2,
        speech_percentage=80.0 if has_speech else 0.0,
        leading_silence_seconds=0.1,
        trailing_silence_seconds=0.1,
        max_pause_seconds=0.0,
        num_speech_segments=1 if has_speech else 0,
        speech_segments=[SpeechSegment(start_seconds=0.1, end_seconds=1.0, duration_seconds=0.9)] if has_speech else [],
        is_reliable=True,
        confidence=0.9
    )
    return noise_class, snr_est, vad_res


def test_confidence_rejects_silence():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.SILENCE, has_speech=False)

    conf = evaluator.evaluate(noise_class=nc, snr_est=snr, vad_res=vad)
    assert conf.directive == ConfidenceDirective.REJECT_UNUSABLE_AUDIO
    assert any("detectable speech" in r for r in conf.reasons)


def test_confidence_rejects_severe_clipping():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.CLIPPING, clipping_pct=10.5)

    conf = evaluator.evaluate(noise_class=nc, snr_est=snr, vad_res=vad)
    assert conf.directive == ConfidenceDirective.REJECT_UNUSABLE_AUDIO
    assert any("clipped" in r for r in conf.reasons)


def test_confidence_requests_repeat_on_honking():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.HONKING, snr_db=15.0)

    conf = evaluator.evaluate(noise_class=nc, snr_est=snr, vad_res=vad)
    assert conf.directive == ConfidenceDirective.REQUEST_REPEAT
    assert any("horn" in r.lower() for r in conf.reasons)


def test_confidence_asks_clarification_on_missing_slots():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.CLEAN)

    conf = evaluator.evaluate(
        noise_class=nc,
        snr_est=snr,
        vad_res=vad,
        intent="RECORD_EXPENSE",
        missing_slots=["amount"]
    )
    assert conf.directive == ConfidenceDirective.ASK_FOR_CLARIFICATION
    assert any("amount" in r for r in conf.reasons)


def test_confidence_requires_confirmation_for_financial_writes():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.CLEAN)

    conf = evaluator.evaluate(
        noise_class=nc,
        snr_est=snr,
        vad_res=vad,
        intent="RECORD_EXPENSE",
        slots={"amount": 350.0, "category": "FUEL"},
        missing_slots=[]
    )
    # Confirmation Firewall rule!
    assert conf.directive == ConfidenceDirective.REQUIRE_EXPLICIT_CONFIRMATION
    assert any("verification" in r.lower() for r in conf.reasons)


def test_confidence_accepts_clean_general_query():
    evaluator = SpeechConfidenceEvaluator()
    nc, snr, vad = make_context(noise_type=NoiseType.CLEAN, snr_db=25.0)

    conf = evaluator.evaluate(
        noise_class=nc,
        snr_est=snr,
        vad_res=vad,
        intent="GENERAL_QUERY",
        intent_confidence=0.95
    )
    assert conf.directive == ConfidenceDirective.ACCEPT_FOR_INTERPRETATION
