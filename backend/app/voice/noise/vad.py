"""
Voice Activity Detection (VAD) Engine for T2T DRIVE.
Segmentates speech from silence intervals, computes leading/trailing silence,
and measures pause distributions using energy-windowing with hangover smoothing.
"""

import io
import wave
import math
import struct
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger("t2t_drive.vad")


@dataclass
class SpeechSegment:
    """Represents a continuous segment of detected voice activity."""
    start_seconds: float
    end_seconds: float
    duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VADResult:
    """Summary of Voice Activity Detection analysis."""
    has_speech: bool
    total_duration_seconds: float
    speech_duration_seconds: float
    silence_duration_seconds: float
    speech_percentage: float
    leading_silence_seconds: float
    trailing_silence_seconds: float
    max_pause_seconds: float
    num_speech_segments: int
    speech_segments: List[SpeechSegment]
    is_reliable: bool
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["speech_segments"] = [s.to_dict() for s in self.speech_segments]
        return d


class VoiceActivityDetector:
    """
    Frame-based Energy VAD with adaptive noise floor tracking and hangover smoothing.
    Optimized for speech commands in Indian vehicles (Tamil, Tanglish, English).
    """

    def __init__(
        self,
        frame_duration_ms: float = 20.0,
        energy_threshold_factor: float = 2.4,
        min_speech_duration_ms: float = 120.0,
        hangover_frames: int = 7  # ~140ms hangover to bridge stop consonants
    ):
        self.frame_duration_ms = frame_duration_ms
        self.energy_threshold_factor = energy_threshold_factor
        self.min_speech_duration_ms = min_speech_duration_ms
        self.hangover_frames = hangover_frames

    def detect(
        self,
        audio_bytes: bytes,
        sample_rate: Optional[int] = None
    ) -> VADResult:
        """
        Executes VAD on WAV audio bytes or raw 16-bit PCM.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            return self._empty_result()

        samples, s_rate = self._extract_samples(audio_bytes, sample_rate)
        if len(samples) == 0 or s_rate <= 0:
            return self._empty_result()

        return self.detect_from_samples(samples, s_rate)

    def detect_from_samples(
        self,
        samples: List[int],
        sample_rate: int = 16000
    ) -> VADResult:
        """
        Executes VAD directly on a list of signed 16-bit PCM integer samples.
        """
        total_samples = len(samples)
        total_duration = total_samples / float(sample_rate)

        if total_duration < 0.05:
            return self._empty_result(total_duration)

        frame_size = int((self.frame_duration_ms / 1000.0) * sample_rate)
        if frame_size < 1:
            frame_size = 1

        num_frames = total_samples // frame_size
        if num_frames == 0:
            return self._empty_result(total_duration)

        # 1. Compute frame energies (RMS)
        frame_energies: List[float] = []
        for i in range(num_frames):
            frame = samples[i * frame_size : (i + 1) * frame_size]
            f_sq = sum(s * s for s in frame)
            f_rms = math.sqrt(f_sq / float(len(frame)))
            frame_energies.append(f_rms)

        # 2. Determine adaptive speech threshold
        sorted_energies = sorted(frame_energies)
        p10_idx = max(0, int(len(sorted_energies) * 0.10))
        p10_val = sorted_energies[p10_idx]

        # If the 10th percentile energy is already substantial (> 200 RMS),
        # the audio has continuous signal throughout without background silence.
        # Set a baseline speech threshold rather than multiplying the loud signal floor.
        if p10_val > 200.0:
            noise_floor = 40.0
            speech_thresh = 100.0
        else:
            noise_floor = max(15.0, p10_val)
            speech_thresh = max(noise_floor * self.energy_threshold_factor, 140.0)

        # 3. Raw speech classification per frame
        raw_speech = [e >= speech_thresh for e in frame_energies]

        # 4. Apply hangover smoothing (bridges unvoiced pauses)
        smoothed = list(raw_speech)
        hangover_counter = 0
        for i in range(num_frames):
            if raw_speech[i]:
                hangover_counter = self.hangover_frames
                smoothed[i] = True
            elif hangover_counter > 0:
                hangover_counter -= 1
                smoothed[i] = True

        # 5. Extract continuous speech segments
        raw_segments: List[Tuple[int, int]] = []
        in_segment = False
        start_frame = 0

        for i in range(num_frames):
            if smoothed[i] and not in_segment:
                in_segment = True
                start_frame = i
            elif not smoothed[i] and in_segment:
                in_segment = False
                raw_segments.append((start_frame, i))

        if in_segment:
            raw_segments.append((start_frame, num_frames))

        # 6. Filter out sub-minimum noise spikes (e.g. key clicks < min_speech_duration_ms)
        min_frames = int((self.min_speech_duration_ms / self.frame_duration_ms))
        valid_segments: List[SpeechSegment] = []

        for sf, ef in raw_segments:
            seg_frames = ef - sf
            if seg_frames >= min_frames:
                start_sec = round((sf * frame_size) / float(sample_rate), 3)
                end_sec = round(min(total_duration, (ef * frame_size) / float(sample_rate)), 3)
                valid_segments.append(
                    SpeechSegment(
                        start_seconds=start_sec,
                        end_seconds=end_sec,
                        duration_seconds=round(end_sec - start_sec, 3)
                    )
                )

        has_speech = len(valid_segments) > 0
        speech_duration = sum(s.duration_seconds for s in valid_segments)
        silence_duration = max(0.0, round(total_duration - speech_duration, 3))
        speech_pct = (speech_duration / total_duration) * 100.0 if total_duration > 0 else 0.0

        # Leading & Trailing silence
        if has_speech:
            leading_silence = valid_segments[0].start_seconds
            trailing_silence = max(0.0, round(total_duration - valid_segments[-1].end_seconds, 3))
        else:
            leading_silence = total_duration
            trailing_silence = 0.0

        # Maximum pause between speech segments
        max_pause = 0.0
        if len(valid_segments) > 1:
            for k in range(len(valid_segments) - 1):
                gap = valid_segments[k + 1].start_seconds - valid_segments[k].end_seconds
                if gap > max_pause:
                    max_pause = gap

        confidence = 0.95 if has_speech and speech_pct > 15.0 else (0.85 if has_speech else 0.98)

        return VADResult(
            has_speech=has_speech,
            total_duration_seconds=round(total_duration, 3),
            speech_duration_seconds=round(speech_duration, 3),
            silence_duration_seconds=round(silence_duration, 3),
            speech_percentage=round(speech_pct, 1),
            leading_silence_seconds=round(leading_silence, 3),
            trailing_silence_seconds=round(trailing_silence, 3),
            max_pause_seconds=round(max_pause, 3),
            num_speech_segments=len(valid_segments),
            speech_segments=valid_segments,
            is_reliable=True,
            confidence=round(confidence, 2)
        )

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _extract_samples(
        self,
        audio_bytes: bytes,
        sample_rate: Optional[int]
    ) -> Tuple[List[int], int]:
        """Safely extracts 16-bit PCM integer samples from WAV bytes."""
        try:
            with io.BytesIO(audio_bytes) as bio:
                with wave.open(bio, "rb") as wf:
                    channels = wf.getnchannels()
                    sr = wf.getframerate()
                    sw = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())

            if sw == 2:
                total_sample_count = len(frames) // 2
                raw_unpacked = struct.unpack(f"<{total_sample_count}h", frames[: total_sample_count * 2])
                if channels == 1:
                    return list(raw_unpacked), sr
                else:
                    mono = [
                        (raw_unpacked[i] + raw_unpacked[i + 1]) // 2
                        for i in range(0, len(raw_unpacked) - 1, 2)
                    ]
                    return mono, sr
            elif sw == 1:
                raw_unpacked = [int(b) for b in frames]
                return [(b - 128) * 256 for b in raw_unpacked], sr
        except Exception as e:
            logger.debug("VAD WAV unpacking fallback: %s", e)

        # If not WAV or failed, try treating as raw 16-bit PCM if sample_rate provided
        sr = sample_rate or 16000
        total_sample_count = len(audio_bytes) // 2
        if total_sample_count > 0:
            try:
                raw_unpacked = struct.unpack(f"<{total_sample_count}h", audio_bytes[: total_sample_count * 2])
                return list(raw_unpacked), sr
            except Exception:
                pass

        return [], sr

    def _empty_result(self, duration: float = 0.0) -> VADResult:
        """Returns empty VAD summary."""
        return VADResult(
            has_speech=False,
            total_duration_seconds=round(duration, 3),
            speech_duration_seconds=0.0,
            silence_duration_seconds=round(duration, 3),
            speech_percentage=0.0,
            leading_silence_seconds=round(duration, 3),
            trailing_silence_seconds=0.0,
            max_pause_seconds=0.0,
            num_speech_segments=0,
            speech_segments=[],
            is_reliable=False,
            confidence=0.50
        )
