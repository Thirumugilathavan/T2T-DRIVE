"""
Synthetic Audio Generator for T2T DRIVE Noise Intelligence Benchmarks.
Generates deterministic 16-bit PCM WAV audio combining synthesized speech formants
with realistic vehicle acoustic environments (engine rumble, traffic, horns, wind).
"""

import io
import math
import random
import struct
import wave
from typing import List, Tuple, Optional


class SyntheticAudioGenerator:
    """
    Synthesizes acoustic waveforms for benchmarking speech recognition
    under reproducible signal-to-noise ratio (SNR) conditions.
    """

    def __init__(self, sample_rate: int = 16000, seed: int = 42):
        self.sample_rate = sample_rate
        self.rng = random.Random(seed)

    def generate_speech_waveform(
        self,
        duration: float = 2.0,
        peak_amplitude: int = 14000,
        f0: float = 135.0
    ) -> List[int]:
        """
        Synthesizes speech-like formant harmonics modulated with a 4Hz syllable rhythm.
        Formants: F0=135Hz, F1=520Hz, F2=1550Hz, F3=2600Hz.
        """
        num_samples = int(self.sample_rate * duration)
        samples = []

        for i in range(num_samples):
            t = i / self.sample_rate

            # 4Hz syllable modulation envelope (soft-rectified sine)
            syllable_mod = max(0.0, math.sin(2 * math.pi * 4.0 * t)) ** 1.5

            # Voiced formant harmonics
            f0_val = math.sin(2 * math.pi * f0 * t) * 0.40
            f1_val = math.sin(2 * math.pi * 520.0 * t) * 0.30
            f2_val = math.sin(2 * math.pi * 1550.0 * t) * 0.20
            f3_val = math.sin(2 * math.pi * 2600.0 * t) * 0.10

            combined = (f0_val + f1_val + f2_val + f3_val) * syllable_mod
            int_val = int(combined * peak_amplitude)
            samples.append(max(-32768, min(32767, int_val)))

        return samples

    def generate_engine_noise(
        self,
        duration: float = 2.0,
        amplitude: int = 4000,
        base_freq: float = 55.0
    ) -> List[int]:
        """
        Synthesizes auto-rickshaw 2-stroke/4-stroke engine vibration.
        Harmonics: 1x, 2x, 3x base frequency (e.g. 55Hz, 110Hz, 165Hz).
        """
        num_samples = int(self.sample_rate * duration)
        samples = []

        for i in range(num_samples):
            t = i / self.sample_rate
            h1 = math.sin(2 * math.pi * base_freq * t) * 0.55
            h2 = math.sin(2 * math.pi * (base_freq * 2) * t) * 0.30
            h3 = math.sin(2 * math.pi * (base_freq * 3) * t) * 0.15
            sub_rumble = math.sin(2 * math.pi * (base_freq * 0.5) * t) * 0.10

            val = int((h1 + h2 + h3 + sub_rumble) * amplitude)
            samples.append(max(-32768, min(32767, val)))

        return samples

    def generate_traffic_noise(
        self,
        duration: float = 2.0,
        amplitude: int = 3000
    ) -> List[int]:
        """
        Synthesizes broadband road/traffic noise using low-pass shaped random noise.
        """
        num_samples = int(self.sample_rate * duration)
        samples = []
        smoothed = 0.0

        for _ in range(num_samples):
            white = (self.rng.random() * 2.0 - 1.0)
            # 1st-order IIR low-pass smoothing (approx 800Hz cutoff)
            smoothed = 0.85 * smoothed + 0.15 * white
            val = int(smoothed * amplitude * 2.2)
            samples.append(max(-32768, min(32767, val)))

        return samples

    def generate_horn_burst(
        self,
        duration: float = 2.0,
        amplitude: int = 22000,
        burst_start: float = 0.7,
        burst_duration: float = 0.6
    ) -> List[int]:
        """
        Synthesizes a piercing dual-tone vehicle horn blast (2800Hz + 3200Hz).
        """
        num_samples = int(self.sample_rate * duration)
        samples = []

        for i in range(num_samples):
            t = i / self.sample_rate
            if burst_start <= t <= (burst_start + burst_duration):
                tone1 = math.sin(2 * math.pi * 2800.0 * t) * 0.5
                tone2 = math.sin(2 * math.pi * 3200.0 * t) * 0.5
                val = int((tone1 + tone2) * amplitude)
            else:
                val = 0
            samples.append(max(-32768, min(32767, val)))

        return samples

    def generate_wind_noise(
        self,
        duration: float = 2.0,
        amplitude: int = 4500
    ) -> List[int]:
        """
        Synthesizes turbulent low-frequency buffeting (< 90Hz).
        """
        num_samples = int(self.sample_rate * duration)
        samples = []
        b0 = 0.0
        b1 = 0.0

        for _ in range(num_samples):
            white = (self.rng.random() * 2.0 - 1.0)
            # Low-pass filter for wind thumps
            b0 = 0.96 * b0 + 0.04 * white
            b1 = 0.94 * b1 + 0.06 * b0
            val = int(b1 * amplitude * 4.0)
            samples.append(max(-32768, min(32767, val)))

        return samples

    def generate_composite(
        self,
        duration: float = 2.0,
        condition: str = "CLEAN",
        target_snr_db: Optional[float] = None
    ) -> Tuple[bytes, List[int], float]:
        """
        Mixes speech and noise according to condition or target SNR.
        Returns (wav_bytes, mono_samples, estimated_snr_db).
        """
        speech = self.generate_speech_waveform(duration=duration, peak_amplitude=12000)

        condition_upper = condition.upper()
        if condition_upper == "CLEAN":
            noise = [0] * len(speech)
            estimated_snr = 30.0

        elif condition_upper == "ENGINE_NOISE":
            # Target ~ 10-14 dB SNR
            noise = self.generate_engine_noise(duration=duration, amplitude=3200)
            estimated_snr = 12.0

        elif condition_upper == "TRAFFIC_NOISE":
            # Target ~ 8-11 dB SNR
            noise = self.generate_traffic_noise(duration=duration, amplitude=2800)
            estimated_snr = 9.5

        elif condition_upper == "HONKING":
            # Sharp horn blast during speech -> ~ 2-4 dB burst SNR
            noise = self.generate_horn_burst(duration=duration, amplitude=24000)
            estimated_snr = 3.2

        elif condition_upper == "WIND_NOISE":
            # Wind buffeting -> ~ 6-9 dB SNR
            noise = self.generate_wind_noise(duration=duration, amplitude=3800)
            estimated_snr = 7.5

        elif condition_upper == "LOW_VOLUME":
            speech = self.generate_speech_waveform(duration=duration, peak_amplitude=900)
            noise = [int((self.rng.random() * 2 - 1) * 80) for _ in range(len(speech))]
            estimated_snr = 15.0

        elif condition_upper == "SILENCE":
            speech = [0] * len(speech)
            noise = [0] * len(speech)
            estimated_snr = 0.0

        elif condition_upper == "CLIPPING":
            speech = self.generate_speech_waveform(duration=duration, peak_amplitude=32767)
            # Clip samples hard
            clipped_speech = []
            for s in speech:
                if s > 24000:
                    clipped_speech.append(32767)
                elif s < -24000:
                    clipped_speech.append(-32768)
                else:
                    clipped_speech.append(s)
            speech = clipped_speech
            noise = [0] * len(speech)
            estimated_snr = 25.0

        else:
            noise = self.generate_traffic_noise(duration=duration, amplitude=2500)
            estimated_snr = 10.0

        # Mix signals
        mixed = []
        for s, n in zip(speech, noise):
            val = max(-32768, min(32767, s + n))
            mixed.append(val)

        # Convert to WAV bytes
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            raw = struct.pack(f"<{len(mixed)}h", *mixed)
            wf.writeframes(raw)

        return bio.getvalue(), mixed, estimated_snr
