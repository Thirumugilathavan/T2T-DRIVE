"""
Audio Metrics Calculator for T2T DRIVE.
Extracts mathematical and acoustic metrics from audio recordings using pure-Python
standard library wave and struct unpacking. Operates deterministically without external
C-compiler dependencies.
"""

import io
import math
import wave
import struct
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger("t2t_drive.audio_metrics")


@dataclass
class AudioMetrics:
    """Acoustic and structural metrics calculated from audio recording."""
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width: int
    total_samples: int
    rms_energy: float
    rms_dbfs: float
    peak_amplitude: int
    peak_dbfs: float
    clipping_samples: int
    clipping_percentage: float
    zero_crossing_rate: float
    estimated_noise_floor_dbfs: float
    silence_percentage: float
    estimated_speech_percentage: float
    dynamic_range_db: float
    crest_factor_db: float
    is_pcm_analyzed: bool
    format: str

    def to_dict(self) -> Dict[str, Any]:
        """Serializes metrics to dictionary."""
        return asdict(self)


class AudioMetricsCalculator:
    """
    High-performance audio metrics calculator for WAV / PCM audio streams.
    Provides fallback handling for compressed audio where PCM cannot be directly extracted.
    """

    def __init__(
        self,
        frame_duration_ms: float = 20.0,
        silence_threshold_rms: float = 60.0,
        clipping_threshold: int = 32750
    ):
        self.frame_duration_ms = frame_duration_ms
        self.silence_threshold_rms = silence_threshold_rms
        self.clipping_threshold = clipping_threshold

    def calculate_from_bytes(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav"
    ) -> AudioMetrics:
        """
        Parses audio bytes and computes comprehensive acoustic metrics.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            return self._empty_metrics(audio_format)

        if audio_format.lower() == "wav":
            try:
                return self._calculate_wav_metrics(audio_bytes)
            except Exception as e:
                logger.warning("WAV metric extraction failed: %s. Falling back to basic metrics.", e)
                return self._fallback_metrics(audio_bytes, audio_format, str(e))

        # Fallback for non-WAV compressed formats (mp3, webm, ogg, m4a)
        return self._fallback_compressed_metrics(audio_bytes, audio_format)

    def unpack_samples(self, wav_bytes: bytes) -> Tuple[List[int], int, int]:
        """
        Public helper to unpack PCM samples, sample_rate, and channels from WAV bytes.
        Returns (samples, sample_rate, channels).
        """
        try:
            with io.BytesIO(wav_bytes) as bio:
                with wave.open(bio, "rb") as wf:
                    channels = wf.getnchannels()
                    sample_rate = wf.getframerate()
                    sample_width = wf.getsampwidth()
                    num_frames = wf.getnframes()
                    raw_pcm = wf.readframes(num_frames)

            if sample_width == 2:
                total_samples = len(raw_pcm) // 2
                raw_unpacked = struct.unpack(f"<{total_samples}h", raw_pcm[: total_samples * 2])
                if channels == 1:
                    samples = list(raw_unpacked)
                else:
                    samples = [(raw_unpacked[i] + raw_unpacked[i + 1]) // 2 for i in range(0, len(raw_unpacked) - 1, 2)]
                return samples, sample_rate, channels
            return [], sample_rate, channels
        except Exception:
            return [], 16000, 1

    def calculate_from_samples(
        self,
        samples: List[int],
        sample_rate: int = 16000,
        channels: int = 1
    ) -> AudioMetrics:
        """
        Direct calculation from an array of signed 16-bit PCM integer samples.
        Useful for unit testing, synthetic audio generation, and benchmarking.
        """
        return self._compute_metrics_from_samples(
            samples=samples,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=2,
            audio_format="wav"
        )

    # ========================================================================
    # INTERNAL IMPLEMENTATION
    # ========================================================================

    def _calculate_wav_metrics(self, wav_bytes: bytes) -> AudioMetrics:
        """Decodes WAV headers and extracts mono 16-bit PCM sample array."""
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                num_frames = wf.getnframes()
                raw_pcm = wf.readframes(num_frames)

        if sample_rate <= 0 or num_frames == 0 or len(raw_pcm) == 0:
            return self._empty_metrics("wav", sample_rate, channels)

        # Unpack samples based on bit depth
        samples: List[int] = []
        if sample_width == 2:  # 16-bit signed PCM
            total_sample_count = len(raw_pcm) // 2
            format_str = f"<{total_sample_count}h"
            raw_unpacked = struct.unpack(format_str, raw_pcm[: total_sample_count * 2])
            if channels == 1:
                samples = list(raw_unpacked)
            else:
                # Downmix stereo to mono by averaging interleaved samples
                samples = [
                    (raw_unpacked[i] + raw_unpacked[i + 1]) // 2
                    for i in range(0, len(raw_unpacked) - 1, 2)
                ]
        elif sample_width == 1:  # 8-bit unsigned PCM
            raw_unpacked = [int(b) for b in raw_pcm]
            # Convert 0..255 to -32768..32767
            if channels == 1:
                samples = [(b - 128) * 256 for b in raw_unpacked]
            else:
                mono_raw = [
                    (raw_unpacked[i] + raw_unpacked[i + 1]) // 2
                    for i in range(0, len(raw_unpacked) - 1, 2)
                ]
                samples = [(b - 128) * 256 for b in mono_raw]
        else:
            # Fallback for 24-bit or 32-bit: read as fallback
            return self._fallback_metrics(wav_bytes, "wav", f"Unsupported sample width: {sample_width}")

        return self._compute_metrics_from_samples(
            samples=samples,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            audio_format="wav"
        )

    def _compute_metrics_from_samples(
        self,
        samples: List[int],
        sample_rate: int,
        channels: int,
        sample_width: int,
        audio_format: str
    ) -> AudioMetrics:
        """Executes core mathematical calculations over integer sample array."""
        n = len(samples)
        if n == 0:
            return self._empty_metrics(audio_format, sample_rate, channels)

        duration = n / float(sample_rate)

        # 1. Peak & Clipping
        peak = 0
        clipping_count = 0
        sum_sq = 0.0
        zero_crossings = 0

        prev_sample = samples[0]
        for s in samples:
            abs_s = abs(s)
            if abs_s > peak:
                peak = abs_s
            if abs_s >= self.clipping_threshold:
                clipping_count += 1
            sum_sq += s * s

            # Zero-crossing rate: change of sign
            if (s >= 0 and prev_sample < 0) or (s < 0 and prev_sample >= 0):
                zero_crossings += 1
            prev_sample = s

        # 2. RMS & Decibel calculations
        mean_sq = sum_sq / float(n)
        rms = math.sqrt(mean_sq)
        rms_dbfs = 20.0 * math.log10(rms / 32768.0) if rms > 0.0 else -96.0
        peak_dbfs = 20.0 * math.log10(peak / 32768.0) if peak > 0.0 else -96.0

        clipping_pct = (clipping_count / float(n)) * 100.0
        zcr = zero_crossings / float(n - 1) if n > 1 else 0.0

        # Crest factor (peak to RMS ratio in dB)
        crest_factor_db = max(0.0, peak_dbfs - rms_dbfs)

        # 3. Frame-based analysis for silence, speech, and noise floor
        frame_size = int((self.frame_duration_ms / 1000.0) * sample_rate)
        if frame_size < 1:
            frame_size = 1

        frame_energies: List[float] = []
        silence_frames = 0
        speech_frames = 0
        num_frames = n // frame_size

        # Default speech threshold: either 150 RMS or 2.5x above minimum silence
        speech_threshold = max(self.silence_threshold_rms * 2.5, 150.0)

        for i in range(num_frames):
            frame = samples[i * frame_size : (i + 1) * frame_size]
            f_sq = sum(fs * fs for fs in frame)
            f_rms = math.sqrt(f_sq / float(len(frame)))
            frame_energies.append(f_rms)

            if f_rms < self.silence_threshold_rms:
                silence_frames += 1
            elif f_rms >= speech_threshold:
                speech_frames += 1

        total_analyzed_frames = max(1, num_frames)
        silence_pct = (silence_frames / float(total_analyzed_frames)) * 100.0
        speech_pct = (speech_frames / float(total_analyzed_frames)) * 100.0

        # 4. Noise floor estimation: 10th percentile of frame energies (minimum statistics)
        if frame_energies:
            sorted_energies = sorted(frame_energies)
            # Pick 10th percentile
            p10_idx = int(len(sorted_energies) * 0.10)
            noise_floor_rms = sorted_energies[p10_idx]
            noise_floor_dbfs = (
                20.0 * math.log10(noise_floor_rms / 32768.0)
                if noise_floor_rms > 0.0
                else -96.0
            )
        else:
            noise_floor_rms = rms
            noise_floor_dbfs = rms_dbfs

        dynamic_range_db = max(0.0, peak_dbfs - noise_floor_dbfs)

        return AudioMetrics(
            duration_seconds=round(duration, 3),
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            total_samples=n,
            rms_energy=round(rms, 2),
            rms_dbfs=round(rms_dbfs, 2),
            peak_amplitude=peak,
            peak_dbfs=round(peak_dbfs, 2),
            clipping_samples=clipping_count,
            clipping_percentage=round(clipping_pct, 3),
            zero_crossing_rate=round(zcr, 4),
            estimated_noise_floor_dbfs=round(noise_floor_dbfs, 2),
            silence_percentage=round(silence_pct, 2),
            estimated_speech_percentage=round(speech_pct, 2),
            dynamic_range_db=round(dynamic_range_db, 2),
            crest_factor_db=round(crest_factor_db, 2),
            is_pcm_analyzed=True,
            format=audio_format
        )

    def _empty_metrics(
        self,
        fmt: str,
        sample_rate: int = 16000,
        channels: int = 1
    ) -> AudioMetrics:
        """Returns baseline metrics for empty or zero-byte audio."""
        return AudioMetrics(
            duration_seconds=0.0,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=2,
            total_samples=0,
            rms_energy=0.0,
            rms_dbfs=-96.0,
            peak_amplitude=0,
            peak_dbfs=-96.0,
            clipping_samples=0,
            clipping_percentage=0.0,
            zero_crossing_rate=0.0,
            estimated_noise_floor_dbfs=-96.0,
            silence_percentage=100.0,
            estimated_speech_percentage=0.0,
            dynamic_range_db=0.0,
            crest_factor_db=0.0,
            is_pcm_analyzed=True,
            format=fmt
        )

    def _fallback_metrics(self, data: bytes, fmt: str, err: str) -> AudioMetrics:
        """Returns estimated metrics when WAV parsing encounters corrupted frames."""
        size = len(data)
        # Approximate duration based on 16kHz 16-bit mono PCM assumption
        approx_duration = size / (16000 * 2) if size > 0 else 0.0
        return AudioMetrics(
            duration_seconds=round(approx_duration, 2),
            sample_rate=16000,
            channels=1,
            sample_width=2,
            total_samples=size // 2,
            rms_energy=0.0,
            rms_dbfs=-96.0,
            peak_amplitude=0,
            peak_dbfs=-96.0,
            clipping_samples=0,
            clipping_percentage=0.0,
            zero_crossing_rate=0.0,
            estimated_noise_floor_dbfs=-96.0,
            silence_percentage=0.0,
            estimated_speech_percentage=0.0,
            dynamic_range_db=0.0,
            crest_factor_db=0.0,
            is_pcm_analyzed=False,
            format=fmt
        )

    def _fallback_compressed_metrics(self, data: bytes, fmt: str) -> AudioMetrics:
        """Basic metadata for compressed formats (MP3/WebM/OGG) where PCM is not extracted."""
        size = len(data)
        # Conservative duration estimate based on standard 32kbps audio stream
        est_duration = size / 4000.0 if size > 0 else 0.0
        return AudioMetrics(
            duration_seconds=round(est_duration, 2),
            sample_rate=16000,
            channels=1,
            sample_width=2,
            total_samples=0,
            rms_energy=500.0,
            rms_dbfs=-36.0,
            peak_amplitude=8000,
            peak_dbfs=-12.0,
            clipping_samples=0,
            clipping_percentage=0.0,
            zero_crossing_rate=0.10,
            estimated_noise_floor_dbfs=-45.0,
            silence_percentage=10.0,
            estimated_speech_percentage=80.0,
            dynamic_range_db=33.0,
            crest_factor_db=24.0,
            is_pcm_analyzed=False,
            format=fmt
        )
