"""
Heuristic Noise Classifier for T2T DRIVE.
Classifies acoustic noise profiles from time-domain and envelope metrics into 10 categories:
CLEAN, ENGINE_NOISE, TRAFFIC_NOISE, HONKING, BACKGROUND_SPEECH, WIND_NOISE,
LOW_VOLUME, CLIPPING, SILENCE, UNKNOWN_NOISE.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from app.voice.noise.audio_metrics import AudioMetrics
from app.voice.noise.snr_estimator import SNREstimate, SNRQuality


class NoiseType(str, Enum):
    """Acoustic noise and quality classifications."""
    CLEAN = "CLEAN"
    ENGINE_NOISE = "ENGINE_NOISE"
    TRAFFIC_NOISE = "TRAFFIC_NOISE"
    HONKING = "HONKING"
    BACKGROUND_SPEECH = "BACKGROUND_SPEECH"
    WIND_NOISE = "WIND_NOISE"
    LOW_VOLUME = "LOW_VOLUME"
    CLIPPING = "CLIPPING"
    SILENCE = "SILENCE"
    UNKNOWN_NOISE = "UNKNOWN_NOISE"


@dataclass
class NoiseClassification:
    """Detailed result of noise classification."""
    primary_category: NoiseType
    secondary_categories: List[NoiseType]
    confidence: float
    supporting_metrics: Dict[str, Any]
    is_reliable: bool
    suggested_strategy: str

    def to_dict(self) -> Dict[str, Any]:
        """Serializes classification to dictionary."""
        d = asdict(self)
        d["primary_category"] = self.primary_category.value
        d["secondary_categories"] = [c.value for c in self.secondary_categories]
        return d


class NoiseClassifier:
    """
    Transparent, heuristic-based acoustic noise classifier.
    Designed for cabin environments of auto-rickshaws, cabs, and Indian street traffic.
    Does not pretend to be a deep-learning neural network; provides explicit, testable rules.
    """

    def __init__(
        self,
        clipping_threshold_pct: float = 0.5,
        low_volume_peak_dbfs: float = -22.0,
        silence_threshold_rms: float = 65.0,
        clean_snr_threshold_db: float = 14.0
    ):
        self.clipping_threshold_pct = clipping_threshold_pct
        self.low_volume_peak_dbfs = low_volume_peak_dbfs
        self.silence_threshold_rms = silence_threshold_rms
        self.clean_snr_threshold_db = clean_snr_threshold_db

    def classify(
        self,
        metrics: AudioMetrics,
        snr_est: Optional[SNREstimate] = None
    ) -> NoiseClassification:
        """
        Classifies audio using metrics and SNR estimation into primary and secondary categories.
        """
        detected: List[Tuple[NoiseType, float, str]] = []  # (Category, confidence, strategy)
        supporting: Dict[str, Any] = {
            "rms_dbfs": metrics.rms_dbfs,
            "peak_dbfs": metrics.peak_dbfs,
            "zcr": metrics.zero_crossing_rate,
            "clipping_pct": metrics.clipping_percentage,
            "crest_factor_db": metrics.crest_factor_db,
            "silence_pct": metrics.silence_percentage,
            "speech_pct": metrics.estimated_speech_percentage,
            "snr_db": snr_est.snr_db if snr_est else None
        }

        # 1. Check for SILENCE first
        if metrics.rms_energy < self.silence_threshold_rms or metrics.silence_percentage >= 90.0:
            return NoiseClassification(
                primary_category=NoiseType.SILENCE,
                secondary_categories=[],
                confidence=0.98,
                supporting_metrics=supporting,
                is_reliable=True,
                suggested_strategy="REQUEST_REPEAT_SPEAK_LOUDER"
            )

        # 2. Check for CLIPPING
        if metrics.clipping_percentage >= self.clipping_threshold_pct or metrics.peak_amplitude >= 32760:
            conf = min(0.99, 0.70 + (metrics.clipping_percentage / 5.0))
            detected.append((NoiseType.CLIPPING, conf, "ATTENUATE_AND_SPEAK_FURTHER"))

        # 3. Check for LOW_VOLUME
        if metrics.peak_dbfs < self.low_volume_peak_dbfs or metrics.rms_dbfs < -38.0:
            conf = 0.90 if metrics.peak_dbfs < -26.0 else 0.75
            detected.append((NoiseType.LOW_VOLUME, conf, "NORMALIZE_AND_SPEAK_CLOSER"))

        # 4. Check for HONKING (Impulsive high-frequency acoustic spike)
        # Horns have sharp attack, high peak-to-RMS crest factor, and sudden energy surge
        if metrics.crest_factor_db >= 14.5 and metrics.zero_crossing_rate >= 0.12 and metrics.clipping_percentage < 2.0:
            horn_conf = min(0.88, 0.60 + (metrics.crest_factor_db - 14.0) * 0.05)
            detected.append((NoiseType.HONKING, horn_conf, "REQUEST_REPEAT_REDUCE_HONK"))

        # 5. Check for ENGINE_NOISE (Stationary low-frequency harmonic drone)
        # Engine vibration produces low zero-crossing rate (< 0.085), low crest factor, and steady noise floor
        if metrics.zero_crossing_rate < 0.085 and metrics.estimated_noise_floor_dbfs > -42.0:
            engine_conf = 0.85 if metrics.zero_crossing_rate < 0.06 else 0.72
            detected.append((NoiseType.ENGINE_NOISE, engine_conf, "HIGH_PASS_FILTER_150HZ"))

        # 6. Check for WIND_NOISE (Erratic low-frequency turbulence)
        if metrics.zero_crossing_rate < 0.05 and metrics.crest_factor_db >= 13.0 and metrics.silence_percentage < 30.0:
            detected.append((NoiseType.WIND_NOISE, 0.78, "HIGH_PASS_FILTER_AND_SHIELD_MIC"))

        # 7. Check for TRAFFIC_NOISE (Broadband background commotion)
        snr_val = snr_est.snr_db if snr_est and snr_est.snr_db is not None else 10.0
        if snr_val < 10.0 and metrics.silence_percentage < 25.0 and metrics.estimated_noise_floor_dbfs > -38.0:
            detected.append((NoiseType.TRAFFIC_NOISE, 0.80, "ADAPTIVE_NOISE_SUPPRESSION"))

        # 8. Check for CLEAN
        if snr_val >= self.clean_snr_threshold_db and metrics.clipping_percentage < 0.1 and metrics.peak_dbfs >= -22.0:
            clean_conf = min(0.98, 0.80 + (snr_val - 14.0) * 0.015)
            detected.append((NoiseType.CLEAN, clean_conf, "PROCEED_AS_IS"))

        # Decision synthesis
        if not detected:
            primary = NoiseType.UNKNOWN_NOISE
            secondaries = []
            confidence = 0.50
            strategy = "PROCEED_WITH_CAUTION"
            is_reliable = False
        else:
            # Sort by confidence descending
            detected.sort(key=lambda x: x[1], reverse=True)
            primary = detected[0][0]
            confidence = detected[0][1]
            strategy = detected[0][2]
            secondaries = [d[0] for d in detected[1:]]
            is_reliable = True

        return NoiseClassification(
            primary_category=primary,
            secondary_categories=secondaries,
            confidence=round(confidence, 2),
            supporting_metrics=supporting,
            is_reliable=is_reliable,
            suggested_strategy=strategy
        )
