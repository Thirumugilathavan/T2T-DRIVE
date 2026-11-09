"""
Adaptive Noise-Aware Audio Preprocessor for T2T DRIVE.
Applies conservative, quality-dependent audio transformations:
1. High-pass IIR filtering (rumble suppression for auto-rickshaw cabin acoustics).
2. Peak-safe dynamic range normalization (prevents clipping).
3. Leading and trailing silence trimming using VAD boundaries.
Always preserves original audio and provides deterministic fallback.
"""

import io
import time
import wave
import math
import struct
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

from app.voice.noise.audio_metrics import AudioMetrics, AudioMetricsCalculator
from app.voice.noise.noise_classifier import NoiseClassification, NoiseType
from app.voice.noise.vad import VADResult

logger = logging.getLogger("t2t_drive.adaptive_preprocessor")


@dataclass
class PreprocessingResult:
    """Detailed audit report of applied audio transformations."""
    original_audio_bytes: bytes
    processed_audio_bytes: bytes
    applied_transformations: List[str]
    processing_duration_ms: float
    is_success: bool
    before_metrics: Dict[str, Any]
    after_metrics: Dict[str, Any]
    fallback_used: bool
    fallback_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Exclude raw byte payloads from JSON serialization
        d.pop("original_audio_bytes", None)
        d.pop("processed_audio_bytes", None)
        return d


class AdaptiveAudioPreprocessor:
    """
    Selects and executes safe audio transformations based on acoustic classification.
    Safely handles 16-bit PCM WAV audio.
    """

    def __init__(
        self,
        highpass_cutoff_hz: float = 120.0,
        target_rms_dbfs: float = -20.0,
        max_gain_factor: float = 4.0,
        min_silence_padding_ms: float = 100.0,
        metrics_calculator: Optional[AudioMetricsCalculator] = None
    ):
        self.cutoff_hz = highpass_cutoff_hz
        self.target_rms_dbfs = target_rms_dbfs
        self.max_gain_factor = max_gain_factor
        self.min_silence_padding_ms = min_silence_padding_ms
        self.metrics_calculator = metrics_calculator or AudioMetricsCalculator()

    def process(
        self,
        audio_bytes: bytes,
        classification: Optional[NoiseClassification] = None,
        vad_result: Optional[VADResult] = None,
        force_clean: bool = False
    ) -> PreprocessingResult:
        """
        Adaptively filters, trims, and normalizes WAV audio bytes.
        If processing fails or deteriorates signal quality, cleanly returns original bytes.
        """
        t0 = time.perf_counter()
        before_metrics = self.metrics_calculator.calculate_from_bytes(audio_bytes, audio_format="wav")

        # Fallback 1: If audio is not PCM WAV or empty, pass through untouched
        if not before_metrics.is_pcm_analyzed or before_metrics.total_samples == 0:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return PreprocessingResult(
                original_audio_bytes=audio_bytes,
                processed_audio_bytes=audio_bytes,
                applied_transformations=["PASSTHROUGH_UNSUPPORTED_FORMAT"],
                processing_duration_ms=round(elapsed, 2),
                is_success=True,
                before_metrics=before_metrics.to_dict(),
                after_metrics=before_metrics.to_dict(),
                fallback_used=False
            )

        # Fallback 2: If audio is pure silence or already clean without need for processing
        if classification and classification.primary_category == NoiseType.SILENCE:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return PreprocessingResult(
                original_audio_bytes=audio_bytes,
                processed_audio_bytes=audio_bytes,
                applied_transformations=["PASSTHROUGH_SILENCE"],
                processing_duration_ms=round(elapsed, 2),
                is_success=True,
                before_metrics=before_metrics.to_dict(),
                after_metrics=before_metrics.to_dict(),
                fallback_used=False
            )

        try:
            # 1. Unpack WAV PCM samples
            samples, sample_rate, channels, sample_width = self._unpack_wav(audio_bytes)
            if not samples:
                raise ValueError("Could not unpack PCM samples from WAV container.")

            transformations: List[str] = []
            cur_samples = list(samples)

            # Determine needed actions from classification
            primary = classification.primary_category if classification else NoiseType.UNKNOWN_NOISE
            secondaries = classification.secondary_categories if classification else []
            all_classes = {primary} | set(secondaries)

            # Action A: High-Pass Filtering for Engine Vibration, Rumble, or Wind
            should_filter = (
                force_clean or
                NoiseType.ENGINE_NOISE in all_classes or
                NoiseType.WIND_NOISE in all_classes or
                before_metrics.zero_crossing_rate < 0.08
            )
            if should_filter and sample_rate >= 8000:
                cur_samples = self._apply_highpass_filter(cur_samples, sample_rate, self.cutoff_hz)
                transformations.append(f"HIGH_PASS_FILTER_{int(self.cutoff_hz)}HZ")

            # Action B: Trimming leading and trailing silence if VAD is available
            if vad_result and vad_result.has_speech and vad_result.speech_segments:
                trimmed_samples, did_trim = self._trim_silence(
                    cur_samples,
                    sample_rate,
                    vad_result.speech_segments,
                    vad_result.total_duration_seconds
                )
                if did_trim:
                    cur_samples = trimmed_samples
                    transformations.append("SILENCE_TRIM")

            # Action C: Peak-Safe RMS Normalization if volume is low
            should_normalize = (
                NoiseType.LOW_VOLUME in all_classes or
                before_metrics.peak_dbfs < -18.0 or
                before_metrics.rms_dbfs < -32.0
            )
            if should_normalize and len(cur_samples) > 0:
                cur_samples, did_norm = self._apply_peak_safe_normalization(cur_samples)
                if did_norm:
                    transformations.append("PEAK_SAFE_NORMALIZATION")

            # If no transformation was warranted
            if not transformations:
                transformations.append("PASSTHROUGH_CLEAN")
                processed_bytes = audio_bytes
            else:
                # 2. Repack into compliant WAV container
                processed_bytes = self._pack_wav(cur_samples, sample_rate, channels=1, sample_width=2)

            after_metrics = self.metrics_calculator.calculate_from_bytes(processed_bytes, audio_format="wav")

            # Quality Check: Ensure preprocessing did not introduce clipping
            if after_metrics.clipping_percentage > 2.0 and before_metrics.clipping_percentage < 0.5:
                logger.warning("Preprocessing introduced clipping (%f%%). Reverting to original audio.", after_metrics.clipping_percentage)
                elapsed = (time.perf_counter() - t0) * 1000.0
                return PreprocessingResult(
                    original_audio_bytes=audio_bytes,
                    processed_audio_bytes=audio_bytes,
                    applied_transformations=transformations,
                    processing_duration_ms=round(elapsed, 2),
                    is_success=False,
                    before_metrics=before_metrics.to_dict(),
                    after_metrics=before_metrics.to_dict(),
                    fallback_used=True,
                    fallback_reason="Preprocessing introduced unwanted audio clipping."
                )

            elapsed = (time.perf_counter() - t0) * 1000.0
            return PreprocessingResult(
                original_audio_bytes=audio_bytes,
                processed_audio_bytes=processed_bytes,
                applied_transformations=transformations,
                processing_duration_ms=round(elapsed, 2),
                is_success=True,
                before_metrics=before_metrics.to_dict(),
                after_metrics=after_metrics.to_dict(),
                fallback_used=False
            )

        except Exception as e:
            logger.error("Adaptive preprocessing failed with error: %s. Using original audio fallback.", e)
            elapsed = (time.perf_counter() - t0) * 1000.0
            return PreprocessingResult(
                original_audio_bytes=audio_bytes,
                processed_audio_bytes=audio_bytes,
                applied_transformations=["FALLBACK_ERROR"],
                processing_duration_ms=round(elapsed, 2),
                is_success=False,
                before_metrics=before_metrics.to_dict(),
                after_metrics=before_metrics.to_dict(),
                fallback_used=True,
                fallback_reason=str(e)
            )

    # ========================================================================
    # SIGNAL PROCESSING ALGORITHMS
    # ========================================================================

    def _apply_highpass_filter(
        self,
        samples: List[int],
        sample_rate: int,
        cutoff_hz: float
    ) -> List[int]:
        """
        Applies a 1st-order IIR high-pass filter:
        y[n] = alpha * (y[n-1] + x[n] - x[n-1])
        alpha = RC / (RC + dt), where dt = 1/fs, RC = 1/(2*pi*fc)
        Pure Python execution, O(N) linear time.
        """
        dt = 1.0 / float(sample_rate)
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        alpha = rc / (rc + dt)

        n = len(samples)
        filtered: List[int] = [0] * n
        if n == 0:
            return filtered

        prev_x = float(samples[0])
        prev_y = 0.0

        for i in range(n):
            cur_x = float(samples[i])
            cur_y = alpha * (prev_y + cur_x - prev_x)

            # Clamp to 16-bit signed integer range
            clamped = int(max(-32768.0, min(32767.0, cur_y)))
            filtered[i] = clamped

            prev_x = cur_x
            prev_y = cur_y

        return filtered

    def _apply_peak_safe_normalization(self, samples: List[int]) -> Tuple[List[int], bool]:
        """
        Boosts volume to achieve target RMS (~ -20 dBFS) without exceeding -1.0 dBFS peak.
        """
        n = len(samples)
        if n == 0:
            return samples, False

        peak = max(abs(s) for s in samples)
        if peak == 0:
            return samples, False

        # Current RMS
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / float(n))
        if rms <= 0:
            return samples, False

        # Desired RMS: -20 dBFS corresponds to approx 3276.8 linear
        target_rms_linear = 32768.0 * (10.0 ** (self.target_rms_dbfs / 20.0))
        desired_gain = target_rms_linear / rms

        # Constrain gain to max_gain_factor
        desired_gain = min(self.max_gain_factor, max(1.0, desired_gain))

        # Peak safety: do not exceed 29500 (approx -0.9 dBFS)
        max_safe_peak = 29500.0
        if peak * desired_gain > max_safe_peak:
            desired_gain = max_safe_peak / float(peak)

        if desired_gain <= 1.05:
            # Negligible boost, skip
            return samples, False

        normalized = [int(s * desired_gain) for s in samples]
        return normalized, True

    def _trim_silence(
        self,
        samples: List[int],
        sample_rate: int,
        segments: List[Any],
        total_duration: float
    ) -> Tuple[List[int], bool]:
        """
        Trims excessive leading and trailing silence outside speech boundaries,
        leaving a small configurable safety padding (e.g. 100ms).
        """
        if not segments:
            return samples, False

        pad_sec = self.min_silence_padding_ms / 1000.0

        speech_start = segments[0].start_seconds
        speech_end = segments[-1].end_seconds

        trim_start_sec = max(0.0, speech_start - pad_sec)
        trim_end_sec = min(total_duration, speech_end + pad_sec)

        # Only trim if leading or trailing silence exceeds 300ms
        if trim_start_sec < 0.25 and (total_duration - trim_end_sec) < 0.25:
            return samples, False

        start_idx = int(trim_start_sec * sample_rate)
        end_idx = int(trim_end_sec * sample_rate)

        trimmed = samples[start_idx:end_idx]
        if len(trimmed) < sample_rate * 0.2:  # Safety: don't produce sub-200ms audio
            return samples, False

        return trimmed, True

    # ========================================================================
    # WAV PACKING & UNPACKING
    # ========================================================================

    def _unpack_wav(self, wav_bytes: bytes) -> Tuple[List[int], int, int, int]:
        """Unpacks 16-bit PCM samples from WAV container."""
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                num_frames = wf.getnframes()
                raw = wf.readframes(num_frames)

        if sample_width != 2:
            return [], sample_rate, channels, sample_width

        total = len(raw) // 2
        unpacked = struct.unpack(f"<{total}h", raw[: total * 2])
        if channels == 1:
            return list(unpacked), sample_rate, channels, sample_width
        else:
            mono = [
                (unpacked[i] + unpacked[i + 1]) // 2
                for i in range(0, len(unpacked) - 1, 2)
            ]
            return mono, sample_rate, 1, sample_width

    def _pack_wav(
        self,
        samples: List[int],
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2
    ) -> bytes:
        """Packs integer samples into a standardized 16-bit mono PCM WAV container."""
        out_bio = io.BytesIO()
        with wave.open(out_bio, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            raw = struct.pack(f"<{len(samples)}h", *samples)
            wf.writeframes(raw)
        return out_bio.getvalue()
