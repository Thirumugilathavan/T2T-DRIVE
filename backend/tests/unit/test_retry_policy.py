"""
Unit tests for NoiseRetryPolicy in T2T DRIVE Noise Intelligence Engine.
Tests multilingual driver guidance (Tamil, Tanglish, English) and bounded retry counters.
"""

import pytest
from app.voice.noise.retry_policy import NoiseRetryPolicy
from app.voice.noise.speech_confidence import ConfidenceDirective
from app.voice.noise.noise_classifier import NoiseType


def test_retry_policy_tamil_guidance_for_honking():
    policy = NoiseRetryPolicy(max_retries=3)
    adv = policy.get_advisory(
        directive=ConfidenceDirective.REQUEST_REPEAT,
        noise_type=NoiseType.HONKING,
        language="ta",
        current_retry_count=0
    )

    assert adv.should_retry is True
    assert adv.retry_count == 1
    assert "ஹாரன்" in adv.display_message
    assert "ஹாரன்" in adv.voice_prompt


def test_retry_policy_tanglish_guidance_for_wind():
    policy = NoiseRetryPolicy(max_retries=3)
    adv = policy.get_advisory(
        directive=ConfidenceDirective.REQUEST_REPEAT,
        noise_type=NoiseType.WIND_NOISE,
        language="tanglish",
        current_retry_count=1
    )

    assert adv.should_retry is True
    assert adv.retry_count == 2
    assert "sound" in adv.display_message.lower() or "mic" in adv.display_message.lower()


def test_retry_policy_english_guidance_for_silence():
    policy = NoiseRetryPolicy(max_retries=3)
    adv = policy.get_advisory(
        directive=ConfidenceDirective.REJECT_UNUSABLE_AUDIO,
        noise_type=NoiseType.SILENCE,
        language="en",
        current_retry_count=0
    )

    assert adv.should_retry is True
    assert "voice detected" in adv.display_message.lower()


def test_retry_policy_max_retries_exceeded():
    policy = NoiseRetryPolicy(max_retries=3)
    adv = policy.get_advisory(
        directive=ConfidenceDirective.REQUEST_REPEAT,
        noise_type=NoiseType.ENGINE_NOISE,
        language="tanglish",
        current_retry_count=3
    )

    assert adv.should_retry is False
    assert adv.reason_code == "MAX_RETRIES_EXCEEDED"
    assert "screen" in adv.display_message.lower() or "button" in adv.display_message.lower()
