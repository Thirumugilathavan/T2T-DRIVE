"""
Signal-to-Noise Ratio (SNR) Estimator for T2T DRIVE.
Implements energy-based minimum statistics frame tracking to estimate speech level
and ambient noise floor. Avoids treating silence as noise-free speech and provides
explicit unreliability markers when estimation is mathematically indefensible.
"""

import math
import logging
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict

from app.voice.noise.audio_metrics import AudioMetrics

logger = logging.getLogger("t2t_drive.snr_estimator")


class SNRQuality(str, Enum):
    """Subjective acoustic quality category based on estimated SNR."""
    GOOD = "GOOD"            # >= 15.0 dB: Clean speech, high recognition fidelity
    MODERATE = "MODERATE"    # 8.0 to < 15.0 dB: Minor noise, generally recognizable
    POOR = "POOR"            # 3.0 to < 8.0 dB: Heavy noise interference, high error risk
    VERY_POOR = "VERY_POOR"  # < 3.0 dB: Intolerable noise, speech drowned
    UNKNOWN = "UNKNOWN"      # Indefensible (pure silence, 0 speech, or corrupted)


@dataclass
class SNREstimate:
    """Estimated SNR results with transparency flags."""
    snr_db: Optional[float]
    quality: SNRQuality
    speech_level_dbfs: Optional[float]
    noise_floor_dbfs: Optional[float]
    estimation_method: str
    is_reliable: bool
    unreliability_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes estimate to dictionary."""
        d = asdict(self)
        d["quality"] = self.quality.value
        return d


class SNREstimator:
    """
    Estimates Signal-to-Noise Ratio (SNR) using frame-level minimum statistics.
    
    Estimation Method:
    1. Segments 16-bit PCM samples into consecutive 20ms analysis frames.
    2. Computes the RMS energy for each frame.
    3. Sorts frame energies to locate the ambient noise floor using the 10th-percentile energy window.
    4. Identifies speech candidate frames where energy exceeds (noise_floor_rms * threshold_factor).
    5. Computes active speech level as the RMS of speech candidate frames.
    6. SNR (dB) = 20 * log10(speech_rms / max(noise_floor_rms, 1.0)).
    
    Limitations:
    - This is an acoustic proxy estimate, not a laboratory dual-channel physical measurement.
    - If the recording is 100% continuous speech with zero pauses, the noise floor estimate
      will be elevated, underestimating true SNR.
    - If the recording is pure synthetic silence (0.0 RMS), SNR is marked UNKNOWN (never infinity).
    """

    def __init__(
        self,
        good_threshold_db: float = 15.0,
        moderate_threshold_db: float = 8.0,
        poor_threshold_db: float = 3.0,
        speech_detection_factor: float = 2.2,
        min_speech_frames_required: int = 3
    ):
        self.good_threshold_db = good_threshold_db
        self.moderate_threshold_db = moderate_threshold_db
        self.poor_threshold_db = poor_threshold_db
        self.speech_detection_factor = speech_detection_factor
        self.min_speech_frames_required = min_speech_frames_required

    def estimate(
        self,
        metrics: AudioMetrics,
        samples: Optional[List[int]] = None
    ) -> SNREstimate:
        """
        Estimates SNR from precomputed AudioMetrics and optional raw PCM samples.
        """
        # Edge Case 1: Empty or zero-duration recording
        if metrics.duration_seconds <= 0.05 or metrics.total_samples == 0:
            return SNREstimate(
                snr_db=None,
                quality=SNRQuality.UNKNOWN,
                speech_level_dbfs=None,
                noise_floor_dbfs=None,
                estimation_method="energy_minimum_statistics_v1",
                is_reliable=False,
                unreliability_reason="Audio recording is empty or duration is under 50ms."
            )

        # Edge Case 2: Pure digital silence (RMS < 5.0 or silence_percentage >= 99%)
        if metrics.rms_energy < 5.0 or metrics.silence_percentage >= 99.0:
            return SNREstimate(
                snr_db=None,
                quality=SNRQuality.UNKNOWN,
                speech_level_dbfs=None,
                noise_floor_dbfs=metrics.rms_dbfs,
                estimation_method="energy_minimum_statistics_v1",
                is_reliable=False,
                unreliability_reason="Recording is completely silent; no speech reference available."
            )

        # Edge Case 3: Severe clipping (> 8% samples clipped)
        if metrics.clipping_percentage > 8.0:
            # We can still estimate but mark as unreliable due to harmonic distortion
            snr_val = max(1.0, metrics.dynamic_range_db * 0.7)
            return SNREstimate(
                snr_db=round(snr_val, 1),
                quality=self._classify_quality(snr_val),
                speech_level_dbfs=metrics.peak_dbfs,
                noise_floor_dbfs=metrics.estimated_noise_floor_dbfs,
                estimation_method="energy_minimum_statistics_v1",
                is_reliable=False,
                unreliability_reason=f"Severe clipping detected ({metrics.clipping_percentage:.1f}%). Dynamic range distorted."
            )

        # Edge Case 4: Very short audio (< 0.4s) has insufficient window for stable noise tracking
        if metrics.duration_seconds < 0.4:
            snr_val = round(max(0.0, metrics.dynamic_range_db * 0.75), 1)
            return SNREstimate(
                snr_db=snr_val,
                quality=self._classify_quality(snr_val),
                speech_level_dbfs=metrics.rms_dbfs,
                noise_floor_dbfs=metrics.estimated_noise_floor_dbfs,
                estimation_method="energy_minimum_statistics_v1",
                is_reliable=False,
                unreliability_reason="Recording duration under 400ms; insufficient window for stable noise tracking."
            )

        # If raw PCM samples are provided, perform frame-level minimum statistics
        if samples and len(samples) > 0 and metrics.sample_rate > 0:
            return self._estimate_from_samples(samples, metrics)

        # Fallback using AudioMetrics summary fields
        return self._estimate_from_metrics_summary(metrics)

    def _estimate_from_samples(
        self,
        samples: List[int],
        metrics: AudioMetrics
    ) -> SNREstimate:
        """Executes detailed frame-by-frame minimum statistics."""
        sample_rate = metrics.sample_rate
        frame_size = int(0.020 * sample_rate)  # 20ms frame
        if frame_size < 1:
            frame_size = 1

        num_frames = len(samples) // frame_size
        if num_frames < 3:
            return self._estimate_from_metrics_summary(metrics)

        frame_energies: List[float] = []
        for i in range(num_frames):
            frame = samples[i * frame_size : (i + 1) * frame_size]
            f_sq = sum(s * s for s in frame)
            f_rms = math.sqrt(f_sq / float(len(frame)))
            frame_energies.append(f_rms)

        sorted_energies = sorted(frame_energies)

        # Noise floor: 10th percentile
        noise_idx = max(0, int(len(sorted_energies) * 0.10))
        noise_floor_rms = max(1.0, sorted_energies[noise_idx])

        # Speech frames threshold
        speech_thresh_rms = max(noise_floor_rms * self.speech_detection_factor, 120.0)
        speech_frames = [e for e in frame_energies if e >= speech_thresh_rms]

        if len(speech_frames) < self.min_speech_frames_required:
            # Low contrast: audio is either continuous noise or faint whisper
            # Use dynamic range as approximate guide
            dyn_range = metrics.dynamic_range_db
            if dyn_range < 5.0:
                snr_val = max(0.5, dyn_range)
                quality = SNRQuality.VERY_POOR
            else:
                snr_val = round(dyn_range * 0.6, 1)
                quality = self._classify_quality(snr_val)

            noise_dbfs = 20.0 * math.log10(noise_floor_rms / 32768.0)
            return SNREstimate(
                snr_db=round(snr_val, 1),
                quality=quality,
                speech_level_dbfs=metrics.rms_dbfs,
                noise_floor_dbfs=round(noise_dbfs, 1),
                estimation_method="energy_minimum_statistics_v1",
                is_reliable=False,
                unreliability_reason="Insufficient speech frames identified above noise floor."
            )

        # Active speech level
        speech_sq_sum = sum(se * se for se in speech_frames)
        speech_rms = math.sqrt(speech_sq_sum / float(len(speech_frames)))

        # SNR in dB
        snr_ratio = speech_rms / noise_floor_rms
        snr_db = 20.0 * math.log10(snr_ratio)

        # Cap unrealistic extremes for physical microphones
        snr_db = min(42.0, max(-5.0, snr_db))

        speech_dbfs = 20.0 * math.log10(speech_rms / 32768.0)
        noise_dbfs = 20.0 * math.log10(noise_floor_rms / 32768.0)
        quality = self._classify_quality(snr_db)

        return SNREstimate(
            snr_db=round(snr_db, 1),
            quality=quality,
            speech_level_dbfs=round(speech_dbfs, 1),
            noise_floor_dbfs=round(noise_dbfs, 1),
            estimation_method="energy_minimum_statistics_v1",
            is_reliable=True,
            unreliability_reason=None
        )

    def _estimate_from_metrics_summary(self, metrics: AudioMetrics) -> SNREstimate:
        """Heuristic estimate based on AudioMetrics precalculated dynamic range."""
        dyn = metrics.dynamic_range_db
        snr_val = round(max(0.0, dyn * 0.75), 1)

        quality = self._classify_quality(snr_val)
        return SNREstimate(
            snr_db=snr_val,
            quality=quality,
            speech_level_dbfs=metrics.rms_dbfs,
            noise_floor_dbfs=metrics.estimated_noise_floor_dbfs,
            estimation_method="metrics_summary_heuristic_v1",
            is_reliable=metrics.is_pcm_analyzed,
            unreliability_reason=None if metrics.is_pcm_analyzed else "PCM samples not directly decoded; using envelope estimate."
        )

    def _classify_quality(self, snr_db: float) -> SNRQuality:
        """Maps numerical SNR decibel value to standardized quality bucket."""
        if snr_db >= self.good_threshold_db:
            return SNRQuality.GOOD
        elif snr_db >= self.moderate_threshold_db:
            return SNRQuality.MODERATE
        elif snr_db >= self.poor_threshold_db:
            return SNRQuality.POOR
        else:
            return SNRQuality.VERY_POOR
