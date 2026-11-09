# T2T DRIVE — Noise-Aware Speech Intelligence Pipeline Architecture

## 1. Executive Summary & Objective

In Indian transit environments—specifically open-cabin auto-rickshaws, city taxis, and shared cabs—acoustic conditions present extreme acoustic interference:
- 2-stroke and 4-stroke engine vibrations creating heavy low-frequency harmonics (40 Hz – 120 Hz).
- Unpredictable high-amplitude vehicle horn blasts (2.8 kHz – 3.2 kHz) exceeding 90 dBA.
- Open-window aerodynamic wind buffeting (< 90 Hz turbulence).
- Dense multi-vehicle street traffic noise.
- Mobile microphone clipping caused by drivers speaking inches away from phone microphones.

The **Phase 6 Noise-Aware Speech Intelligence Pipeline** introduces an acoustic pre-flight inspection and adaptive signal conditioning layer positioned directly between incoming driver audio streams and cloud/local Automatic Speech Recognition (ASR / Gnani Prisma STT).

```
[Driver Voice + Vehicle Noise]
              │
              ▼
    [Audio Pre-flight Check]
              │
     ┌────────┴────────┐
     ▼                 ▼
[Pure Silence /   [Acoustic Analysis & Preprocessing]
 Severe Distortion]   ├── AudioMetricsCalculator (RMS, Peak, ZCR, Floor)
     │                ├── SNREstimator (Minimum Statistics)
     ▼                ├── NoiseClassifier (10 Acoustic Categories)
[Early Reject]        ├── VoiceActivityDetector (Adaptive VAD + Hangover)
(No STT Call)         └── AdaptiveAudioPreprocessor
                           ├── 120Hz High-Pass IIR Filter
                           ├── Silence Trimming (100ms Margin)
                           └── Peak-Safe RMS Normalization
                               │
                               ▼
                   [Cleaned / Conditioned Audio]
                               │
                               ▼
                   [Gnani Prisma STT Engine]
                               │
                               ▼
                 [LangGraph Conversational Agent]
                               │
                               ▼
                 [Confirmation Firewall] ────► [Financial Ledger Write]
```

---

## 2. Signal Processing Algorithms

### 2.1 Waveform Ingestion & Audio Metrics (`audio_metrics.py`)
Incoming audio in WAV container format is decoded into signed 16-bit PCM integer samples (\(-32768\) to \(+32767\)). Stereo audio is automatically downmixed to single-channel mono by sample-level averaging.

1. **RMS Energy & Decibels Relative to Full Scale (dBFS):**
   \[
   RMS = \sqrt{\frac{1}{N} \sum_{i=0}^{N-1} x[i]^2}
   \]
   \[
   RMS_{dBFS} = 20 \log_{10} \left( \frac{RMS}{32768.0} \right)
   \]
   A physical digital noise floor of \(-96.0\text{ dBFS}\) is enforced to prevent mathematical singularities on pure silence.

2. **Peak Amplitude & Crest Factor:**
   \[
   Peak = \max_{i} |x[i]|
   \]
   \[
   Crest_{dB} = 20 \log_{10} \left( \frac{Peak}{RMS + \epsilon} \right)
   \]
   Crest factor quantifies the peakedness of the audio: high crest factors (\(> 14.5\text{ dB}\)) flag sudden impulse events (horn honks or door slams), while low crest factors (\(< 10\text{ dB}\)) denote steady drone noise (engine vibration).

3. **Zero-Crossing Rate (ZCR):**
   \[
   ZCR = \frac{1}{N-1} \sum_{i=1}^{N-1} \mathbb{I}\left( \text{sgn}(x[i]) \neq \text{sgn}(x[i-1]) \right)
   \]
   Low-frequency engine rumble and wind noise exhibit low ZCR (\(< 0.08\)), whereas speech unvoiced fricatives and vehicle horns produce elevated ZCR (\(> 0.12\)).

4. **Clipping Percentage:**
   Samples where \(|x[i]| \ge 32760\) are flagged as clipped. If clipping exceeds \(1.0\%\), the signal is classified as clipped; if clipping exceeds \(8.0\%\), the recording is deemed unrecoverable and rejected before calling cloud STT.

---

### 2.2 Signal-to-Noise Ratio (SNR) Estimation (`snr_estimator.py`)
The pipeline uses **energy-based minimum statistics** across 20ms analysis frames:
1. Divide audio into 20ms contiguous frames.
2. Calculate RMS energy for each frame.
3. Sort frame energies:
   - Noise floor estimate \(RMS_{noise}\) is derived from the 10th percentile frame energy.
   - Speech energy estimate \(RMS_{speech}\) is computed across active frames where \(E_{frame} \ge 2.2 \times RMS_{noise}\).
4. Estimated SNR is computed:
   \[
   SNR_{dB} = 20 \log_{10} \left( \frac{RMS_{speech}}{RMS_{noise}} \right)
   \]
5. Quality categorization:
   - **GOOD**: \(SNR \ge 15.0\text{ dB}\)
   - **MODERATE**: \(8.0\text{ dB} \le SNR < 15.0\text{ dB}\)
   - **POOR**: \(3.0\text{ dB} \le SNR < 8.0\text{ dB}\)
   - **VERY_POOR**: \(SNR < 3.0\text{ dB}\)
   - **UNKNOWN**: Silence, severe clipping, or duration \(< 400\text{ ms}\) (marked as unreliable).

---

### 2.3 Acoustic Noise Classification (`noise_classifier.py`)
Heuristic multi-metric decision tree classifying 10 acoustic conditions:
| Acoustic Category | Diagnostic Heuristics | Recommended Pipeline Action |
|:---|:---|:---|
| `SILENCE` | Silence \(\ge 90\%\) or \(RMS < -50\text{ dBFS}\) | Early reject, prompt driver to speak |
| `CLIPPING` | Clipping samples \(> 1.0\%\) | Attenuate or reject if \(> 8\%\) |
| `LOW_VOLUME` | \(RMS < -35\text{ dBFS}\), Peak \(< -18\text{ dBFS}\) | Peak-safe RMS normalization |
| `ENGINE_NOISE` | \(ZCR < 0.085\), Noise floor \(> -42\text{ dBFS}\) | 120Hz high-pass IIR filtering |
| `HONKING` | Crest factor \(\ge 14.5\text{ dB}\), \(ZCR \ge 0.12\) | Request repeat after horn clears |
| `WIND_NOISE` | \(ZCR < 0.05\), Crest \(\ge 13\text{ dB}\) | High-pass filter & shield microphone |
| `TRAFFIC_NOISE` | Broadband energy, \(SNR < 10\text{ dB}\) | Adaptive filtering & speech normalization |
| `CLEAN` | \(SNR \ge 16\text{ dB}\), Clipping \(= 0\%\) | Pass-through untouched |

---

### 2.4 Voice Activity Detection (`vad.py`)
Frame-level energy tracking with hangover smoothing:
- Frame size: 20ms (\(320\text{ samples}\) at \(16\text{ kHz}\)).
- Adaptive threshold: If background silence is present, threshold is \(2.4 \times P_{10}\). If audio has continuous energy throughout (\(P_{10} > 200\text{ RMS}\)), threshold is set to absolute speech level (\(100\text{ RMS}\)).
- **Hangover smoothing**: 8 frames (\(160\text{ ms}\)) bridge inter-syllable unvoiced pauses so natural speech is not fragmented.
- Segment extraction yields exact start/end timestamps, leading silence, and trailing silence.

---

### 2.5 Adaptive Audio Preprocessing (`adaptive_preprocessor.py`)
1. **High-Pass IIR Filter (< 120 Hz):**
   Single-pole high-pass difference equation:
   \[
   y[n] = \alpha \cdot (y[n-1] + x[n] - x[n-1])
   \]
   where \(\alpha = \frac{1}{1 + 2\pi f_c \Delta t}\) (\(f_c = 120\text{ Hz}\)). Attenuates engine rumble and wind buffeting by \(> 12\text{ dB}\) while preserving driver vocal fundamentals (\(> 130\text{ Hz}\)).
2. **Silence Trimming:**
   Trims leading and trailing dead time based on VAD speech segments, retaining a conservative \(100\text{ ms}\) padding margin to avoid clipping word onsets or codas.
3. **Peak-Safe RMS Normalization:**
   Scales quiet audio up toward \(-20\text{ dBFS}\) RMS, strictly bounding the gain so that peak amplitude never exceeds \(-1.0\text{ dBFS}\) (\(29197 / 32768\)).
4. **Lossless Safety Fallback:**
   If preprocessing introduces digital clipping (\(> 0.1\%\)) or reduces overall energy below usable thresholds, the preprocessor automatically aborts and returns the pristine original audio bytes.

---

## 3. Multi-Dimensional Confidence & Confirmation Firewall

To prevent noisy acoustic conditions from triggering mistaken financial ledger writes, `SpeechConfidenceEvaluator` synthesizes 5 orthogonal confidence dimensions:

```
[Acoustic Confidence] ──┐
[STT Confidence]      ──┼──► [SpeechConfidenceEvaluator] ──► Directive:
[Language Confidence] ──┤                                      ├── ACCEPT_FOR_INTERPRETATION
[Intent Confidence]   ──┤                                      ├── REQUIRE_EXPLICIT_CONFIRMATION
[Slot Confidence]     ──┘                                      ├── ASK_FOR_CLARIFICATION
                                                               ├── REQUEST_REPEAT
                                                               └── REJECT_UNUSABLE_AUDIO
```

### The Confirmation Firewall Rule:
Regardless of acoustic quality or confidence scores, **ALL** write operations (`RECORD_EXPENSE`, `RECORD_INCOME`, `CALCULATE_SETTLEMENT`, `ADD_MAINTENANCE`, `PAY_CHALLAN`) MUST pass through the Confirmation Firewall:
- The agent presents the structured transaction proposal with specific Tamil/Tanglish/English voice output.
- No write occurs until the driver explicitly utters confirmation ("Sari", "Confirm", "Aama").

---

## 4. Localized Driver Advisories (`retry_policy.py`)

When acoustic conditions deteriorate, the system delivers driver-safe, non-technical advisories:
- **Vehicle Horn Blast:**
  - *Tamil:* "ஹாரன் சத்தம் அதிகம். சத்தம் குறைந்ததும் மீண்டும் கூறவும்."
  - *Tanglish:* "Horn sound jasthi irundhudhu. Marubadi theliva sollunga."
  - *English:* "Loud horn blast detected. Please repeat clearly."
- **Wind Turbulence:**
  - *Tanglish:* "Kaathu sound jasthi irukku. Window saathi pesunga."
- **Low Volume:**
  - *Tanglish:* "Voice romba low-aa irukku. Konjam satham-aa sollunga."
- **Max Retries Exceeded (3 Retries):**
  - Switches gracefully to manual UI input: "Thodarndhu sound jasthi irukku. Screen-la irukura button use pannunga."

---

## 5. API Reference

### 5.1 POST `/api/voice/analyze-audio`
Upload an audio file to receive instantaneous acoustic telemetry without triggering conversational intent or financial actions.

**Request:** `multipart/form-data`
- `file`: WAV audio recording
- `language`: `tanglish` | `tamil` | `english`

**Response (`200 OK`):**
```json
{
  "success": true,
  "data": {
    "overall_quality": "GOOD",
    "should_proceed_to_stt": true,
    "metrics": {
      "sample_rate": 16000,
      "duration_seconds": 1.8,
      "rms_dbfs": -18.4,
      "peak_dbfs": -5.2,
      "clipping_percentage": 0.0,
      "zero_crossing_rate": 0.088
    },
    "snr": {
      "snr_db": 22.4,
      "quality": "GOOD",
      "is_reliable": true
    },
    "noise_classification": {
      "primary_category": "CLEAN",
      "confidence": 0.92,
      "suggested_strategy": "PROCEED_AS_IS"
    },
    "vad": {
      "has_speech": true,
      "speech_duration_seconds": 1.4,
      "leading_silence_seconds": 0.2
    },
    "confidence": {
      "directive": "REQUIRE_EXPLICIT_CONFIRMATION"
    }
  }
}
```
