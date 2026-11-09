"""
Noise Service & Audio Intelligence Facade for T2T DRIVE.
Orchestrates metrics extraction, SNR estimation, noise classification, VAD,
adaptive preprocessing, multi-dimensional confidence analysis, and retry advisories.
Provides a unified pre-flight pipeline for speech input.
"""

import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict

from app.voice.noise.audio_metrics import AudioMetricsCalculator, AudioMetrics
from app.voice.noise.snr_estimator import SNREstimator, SNREstimate, SNRQuality
from app.voice.noise.noise_classifier import NoiseClassifier, NoiseClassification, NoiseType
from app.voice.noise.vad import VoiceActivityDetector, VADResult
from app.voice.noise.adaptive_preprocessor import AdaptiveAudioPreprocessor, PreprocessingResult
from app.voice.noise.speech_confidence import (
    SpeechConfidenceEvaluator,
    ConfidenceDirective,
    MultiDimensionalConfidence
)
from app.voice.noise.retry_policy import NoiseRetryPolicy, RetryAdvisory

logger = logging.getLogger("t2t_drive.noise_service")


@dataclass
class AudioAnalysisReport:
    """Comprehensive acoustic and noise intelligence report for an audio recording."""
    overall_quality: str  # "GOOD", "MODERATE", "POOR", "VERY_POOR", "UNUSABLE"
    should_proceed_to_stt: bool
    rejection_reason: Optional[str]
    metrics: Dict[str, Any]
    snr: Dict[str, Any]
    noise_classification: Dict[str, Any]
    vad: Dict[str, Any]
    preprocessing: Optional[Dict[str, Any]] = None
    confidence: Optional[Dict[str, Any]] = None
    retry_advisory: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NoiseService:
    """
    Unified entry point for Phase 6 Noise-Aware Speech Intelligence.
    Can be used standalone (e.g. /api/voice/analyze-audio) or embedded inside VoiceService.
    """

    def __init__(
        self,
        metrics_calculator: Optional[AudioMetricsCalculator] = None,
        snr_estimator: Optional[SNREstimator] = None,
        noise_classifier: Optional[NoiseClassifier] = None,
        vad: Optional[VoiceActivityDetector] = None,
        preprocessor: Optional[AdaptiveAudioPreprocessor] = None,
        confidence_evaluator: Optional[SpeechConfidenceEvaluator] = None,
        retry_policy: Optional[NoiseRetryPolicy] = None,
        enable_adaptive_preprocessing: bool = True
    ):
        self.metrics_calculator = metrics_calculator or AudioMetricsCalculator()
        self.snr_estimator = snr_estimator or SNREstimator()
        self.noise_classifier = noise_classifier or NoiseClassifier()
        self.vad = vad or VoiceActivityDetector()
        self.preprocessor = preprocessor or AdaptiveAudioPreprocessor(metrics_calculator=self.metrics_calculator)
        self.confidence_evaluator = confidence_evaluator or SpeechConfidenceEvaluator()
        self.retry_policy = retry_policy or NoiseRetryPolicy()
        self.enable_preprocessing = enable_adaptive_preprocessing

    def analyze_audio(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "tanglish",
        current_retry_count: int = 0
    ) -> AudioAnalysisReport:
        """
        Executes full pre-flight acoustic evaluation on audio bytes without modifying them.
        """
        # 1. Acoustic Metrics
        metrics = self.metrics_calculator.calculate_from_bytes(audio_bytes, audio_format=audio_format)

        # 2. Extract PCM samples if WAV
        samples = None
        if metrics.is_pcm_analyzed and audio_format == "wav":
            samples, _, _, _ = self.preprocessor._unpack_wav(audio_bytes)

        # 3. SNR Estimation
        snr = self.snr_estimator.estimate(metrics, samples=samples)

        # 4. Noise Classification
        noise_class = self.noise_classifier.classify(metrics, snr_est=snr)

        # 5. Voice Activity Detection (VAD)
        if samples and metrics.sample_rate > 0:
            vad_res = self.vad.detect_from_samples(samples, metrics.sample_rate)
        else:
            vad_res = self.vad.detect(audio_bytes)

        # 6. Confidence Directive
        conf = self.confidence_evaluator.evaluate(
            noise_class=noise_class,
            snr_est=snr,
            vad_res=vad_res,
            intent=None,
            intent_confidence=0.80
        )

        # 7. Check if recording is usable for STT
        # Only outright unusable audio (silence, no speech, massive clipping distortion)
        # rejects early before calling STT. Noisy audio proceeds to STT while reporting advisory.
        should_proceed = conf.directive != ConfidenceDirective.REJECT_UNUSABLE_AUDIO
        rejection_reason = conf.reasons[0] if not should_proceed and conf.reasons else None

        # 8. Retry Advisory if unusable or degraded
        retry_adv = None
        if not should_proceed or conf.directive in (
            ConfidenceDirective.ASK_FOR_CLARIFICATION,
            ConfidenceDirective.REQUIRE_EXPLICIT_CONFIRMATION
        ):
            retry_adv = self.retry_policy.get_advisory(
                directive=conf.directive,
                noise_type=noise_class.primary_category,
                language=language,
                current_retry_count=current_retry_count
            )

        # Overall quality mapping
        if noise_class.primary_category == NoiseType.SILENCE or not vad_res.has_speech:
            quality = "UNUSABLE"
        elif snr.quality == SNRQuality.GOOD and noise_class.primary_category == NoiseType.CLEAN:
            quality = "GOOD"
        elif snr.quality in (SNRQuality.GOOD, SNRQuality.MODERATE):
            quality = "MODERATE"
        elif snr.quality == SNRQuality.POOR:
            quality = "POOR"
        else:
            quality = "VERY_POOR"

        return AudioAnalysisReport(
            overall_quality=quality,
            should_proceed_to_stt=should_proceed,
            rejection_reason=rejection_reason,
            metrics=metrics.to_dict(),
            snr=snr.to_dict(),
            noise_classification=noise_class.to_dict(),
            vad=vad_res.to_dict(),
            preprocessing=None,
            confidence=conf.to_dict(),
            retry_advisory=retry_adv.to_dict() if retry_adv else None
        )

    def prepare_for_stt(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "tanglish",
        current_retry_count: int = 0
    ) -> Tuple[bytes, AudioAnalysisReport, Optional[PreprocessingResult]]:
        """
        Pre-flight pipeline for STT:
        1. Analyzes audio.
        2. Applies adaptive preprocessing (filtering, normalization, trimming) if enabled.
        3. Returns (optimal_audio_bytes, analysis_report, preprocessing_result).
        """
        report = self.analyze_audio(
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            language=language,
            current_retry_count=current_retry_count
        )

        prep_res: Optional[PreprocessingResult] = None
        optimal_bytes = audio_bytes

        if self.enable_preprocessing and audio_format == "wav" and report.should_proceed_to_stt:
            # Reconstruct objects for preprocessor
            metrics_obj = self.metrics_calculator.calculate_from_bytes(audio_bytes, audio_format="wav")
            snr_obj = self.snr_estimator.estimate(metrics_obj)
            noise_obj = self.noise_classifier.classify(metrics_obj, snr_est=snr_obj)
            vad_obj = self.vad.detect(audio_bytes)

            prep_res = self.preprocessor.process(
                audio_bytes=audio_bytes,
                classification=noise_obj,
                vad_result=vad_obj
            )
            optimal_bytes = prep_res.processed_audio_bytes
            report.preprocessing = prep_res.to_dict()

        return optimal_bytes, report, prep_res
