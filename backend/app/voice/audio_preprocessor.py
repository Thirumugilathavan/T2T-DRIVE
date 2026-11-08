"""
Audio Preprocessing and Inspection Module for T2T DRIVE.
Inspects audio properties (sample rate, channels, duration),
detects silent recordings, and safely prepares audio for Prisma STT.
"""

import io
import math
import wave
import struct
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("t2t_drive.audio_preprocessor")


class AudioPreprocessor:
    """
    Conservative audio inspector and preprocessor.
    Safely inspects WAV audio and provides graceful fallback for compressed streams (webm, mp3).
    """

    def __init__(
        self,
        min_duration_seconds: float = 0.2,
        max_duration_seconds: float = 60.0,
        silence_threshold_rms: float = 50.0
    ):
        self.min_duration = min_duration_seconds
        self.max_duration = max_duration_seconds
        self.silence_threshold = silence_threshold_rms

    def inspect_and_preprocess(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav"
    ) -> Dict[str, Any]:
        """
        Inspects audio bytes, calculates duration/channels/sample_rate where possible,
        detects empty or silent recordings, and returns normalized metadata.
        """
        result = {
            "is_processable": True,
            "is_silent": False,
            "duration_seconds": None,
            "sample_rate": None,
            "channels": None,
            "audio_bytes": audio_bytes,
            "error": None
        }

        # Handle WAV format specifically with Python's built-in wave module
        if audio_format == "wav":
            try:
                with io.BytesIO(audio_bytes) as bio:
                    with wave.open(bio, "rb") as wf:
                        channels = wf.getnchannels()
                        sample_rate = wf.getframerate()
                        sample_width = wf.getsampwidth()
                        num_frames = wf.getnframes()

                        duration = num_frames / float(sample_rate) if sample_rate > 0 else 0.0

                        result["duration_seconds"] = round(duration, 2)
                        result["sample_rate"] = sample_rate
                        result["channels"] = channels

                        # Duration constraints
                        if duration < self.min_duration:
                            result["is_processable"] = False
                            result["error"] = f"Audio recording too short ({duration:.2f}s). Minimum {self.min_duration}s required."
                            return result

                        if duration > self.max_duration:
                            result["is_processable"] = False
                            result["error"] = f"Audio recording too long ({duration:.2f}s). Maximum {self.max_duration}s allowed."
                            return result

                        # Check for silence in WAV PCM data (sample width 2 = 16-bit)
                        if sample_width == 2 and num_frames > 0:
                            frames = wf.readframes(min(num_frames, 32000))  # sample up to 1-2 seconds
                            rms = self._calculate_rms_16bit(frames)
                            if rms < self.silence_threshold:
                                result["is_silent"] = True
                                result["is_processable"] = False
                                result["error"] = "Audio recording appears to be completely silent."
                                return result

            except Exception as e:
                logger.warning("WAV header inspection failed (falling back to raw passthrough): %s", e)

        # For compressed formats (webm, mp3, ogg), estimate duration based on file size if needed
        # and pass through cleanly to Prisma
        return result

    @staticmethod
    def _calculate_rms_16bit(pcm_data: bytes) -> float:
        """Calculates Root-Mean-Square (RMS) amplitude of 16-bit PCM audio samples."""
        num_samples = len(pcm_data) // 2
        if num_samples == 0:
            return 0.0

        try:
            format_str = f"<{num_samples}h"
            samples = struct.unpack(format_str, pcm_data[: num_samples * 2])
            sum_squares = sum(s * s for s in samples)
            mean_square = sum_squares / float(num_samples)
            return math.sqrt(mean_square)
        except Exception:
            return 100.0  # Inconclusive, assume not silent
