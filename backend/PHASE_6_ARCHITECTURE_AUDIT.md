# T2T DRIVE — Phase 6 Architecture & Technical Audit
## Advanced Noise-Aware Speech Intelligence, Audio Quality Analysis and Recognition Benchmarking

**Project:** T2T DRIVE (A Noise-Aware, Multilingual AI Voice Co-Pilot for Auto-Rickshaw and Cab Drivers)  
**Date:** November 2026  
**Auditor:** Senior Voice & Audio AI Architect  
**Scope:** In-depth evaluation of current Phase 1–5 backend voice pipeline, identification of technical gaps in ambient noise handling, compatibility assessment for Windows / Python 3.14.7, and detailed design roadmap for Phase 6 implementation.

---

## 1. Executive Overview

T2T DRIVE operates in an exceptionally demanding acoustic environment: the cabin of Indian auto-rickshaws and cabs. Drivers routinely operate under:
- Two-stroke / four-stroke low-frequency engine vibration and acoustic rumble (40 Hz – 250 Hz).
- High-intensity, impulsive horn blasts from adjacent traffic (2 kHz – 4 kHz, often exceeding 90 dB SPL).
- Turbulent wind shear across open vehicle cabins and side curtains.
- Continuous urban traffic noise, tire friction, and ambient pedestrian conversations.
- Dynamic distance from the smartphone microphone, leading to low volume, clipping, and fluctuating Signal-to-Noise Ratios (SNR).

In Phase 4, a foundational voice integration was created with Gnani Prisma STT (speech-to-text) and Gnani Timbre TTS (text-to-speech), managed through `VoiceService` and guarded by the Phase 2 Financial Confirmation Firewall. However, the current audio pipeline treats audio as a binary asset (valid format vs. invalid format), with only primitive duration and silence thresholds. It cannot measure SNR, classify noise types, detect speech segments vs. pauses (VAD), adaptively filter or normalize degraded audio, assess multi-dimensional confidence, or guide drivers with context-sensitive audio clarification prompts.

Phase 6 implements a modular, mathematically rigorous, and production-hardened **Audio Quality Analysis & Noise Intelligence Engine** integrated directly into the voice pipeline.

---

## 2. Comprehensive Audit of Existing Voice & Agent Architecture

### 2.1 Audio Ingestion & Validation (`app.voice.audio_validator`)
- **Current Capabilities:**
  - Validates file sizes against `max_upload_mb` (default: 10 MB).
  - Checks magic bytes for WAV (`RIFF...WAVE`), OGG (`OggS`), WebM (`\x1a\x45\xdf\xa3`), MP3 (`ID3` or frame syncs), M4A (`ftyp`), and AAC.
  - Manages secure temporary files using cryptographically random hex tokens (`t2t_voice_<hex>.<ext>`) with guaranteed cleanup via context manager.
- **Existing Limitations:**
  - Treats all valid audio bytes equally regardless of whether they contain intelligible speech or 100% engine rumble.
  - No verification of sample clipping, DC offset, or dynamic range.

### 2.2 Audio Preprocessing & Inspection (`app.voice.audio_preprocessor`)
- **Current Capabilities:**
  - Inspects WAV headers using standard library `wave` to extract channels, sample rate, sample width, and frame count.
  - Implements basic duration bounds (`min_duration_seconds=0.2`, `max_duration_seconds=60.0`).
  - Computes basic 16-bit PCM Root-Mean-Square (RMS) amplitude on up to 32,000 frames using `struct.unpack("<...h")`.
  - Flags complete silence if RMS < 50.0.
- **Existing Limitations:**
  - **No SNR Estimation:** Treats quiet speech and loud background rumble identically.
  - **No Voice Activity Detection (VAD):** Cannot distinguish speech segments from leading/trailing vehicle idle rumble.
  - **No Noise Classification:** Does not distinguish horn honks, engine rumble, traffic roar, wind shear, or clipping.
  - **No Signal Processing / Filtering:** Cannot apply high-pass filtering (rumble removal), normalization, or spectral attenuation. Passes raw audio straight to the cloud STT API.

### 2.3 STT & TTS Providers (`app.voice.prisma_adapter`, `app.voice.timbre_adapter`)
- **Current Capabilities:**
  - `PrismaAdapter`: REST v3.0 multipart client sending audio, language hint, and context-boosting domain keyterms (`diesel`, `petrol`, `savari`, `settlement`, etc.).
  - `MockPrismaAdapter`: Deterministic offline mock responding to language hints with mock Tanglish/Tamil/English transcripts.
  - `TimbreAdapter` & `MockTimbreAdapter`: Synthesizes speech to WAV bytes / Base64.
- **Existing Limitations:**
  - Cloud STT providers in production frequently return transcripts even for noise or honks, or return empty transcripts when noise drowns speech. The pipeline currently has no local pre-flight gate to decide if audio is suitable for STT before incurring network latency and API costs.
  - Confidence returned by STT is often `None` or opaque. The system lacks local confidence modeling.

### 2.4 Agent NLU, Graph & Confidence Handling (`app.agent.*`)
- **Current Capabilities:**
  - LangGraph workflow coordinates multi-turn sessions with thread isolation.
  - `MultilingualNLU`: Rule and regex-based intent classification across Tamil script, Tanglish, and English with slot extraction.
  - Strict confirmation firewall: Writes (`RECORD_EXPENSE`, `RECORD_INCOME`, `SETTLEMENT`, `MAINTENANCE`) create `PENDING` actions that require explicit driver confirmation (`AWAITING_CONFIRMATION` -> `CONFIRM_ACTION`).
- **Existing Limitations:**
  - Confidence in `MultilingualNLU` is purely semantic/lexical (e.g. 0.90 if amount found, 0.75 if missing). It is completely decoupled from acoustic confidence.
  - When speech is muffled or degraded by noise, NLU may extract a distorted amount or incorrect intent without knowing that the acoustic signal had an SNR of -2 dB.

### 2.5 REST API Routes (`app.routes.voice_routes`)
- **Current Capabilities:**
  - `POST /api/voice/transcribe` & `POST /api/speech/transcribe`
  - `POST /api/voice/chat` (unified end-to-end voice co-pilot)
  - `POST /api/voice/speak` & `POST /api/speech/speak`
  - `GET /api/voice/capabilities`
- **Existing Limitations:**
  - No standalone endpoint for audio quality inspection (`POST /api/voice/analyze-audio`).
  - API response envelopes in `VoiceTurnResponse` lack structured acoustic metrics (SNR, noise class, VAD stats, quality category, processing latency).

### 2.6 Frontend Audio Feedback (`frontend/js/voice.js`, `frontend/index.html`)
- **Current Capabilities:**
  - HTML5 Web Audio API visualizer drawing real-time microphone waveforms.
  - Push-to-Talk (PTT) button, file upload, and manual text fallback.
- **Existing Limitations:**
  - Visual feedback is generic ("Transcribing with Gnani Indic-ASR...").
  - Does not display audio quality status (Good, Moderate, Poor), noise warnings (e.g., "Engine noise high - speak closer"), or retry advisories to the driver.

---

## 3. Python 3.14.7 & Windows Compatibility Assessment

A critical engineering constraint in this environment is **Python 3.14.7 on Windows**:
1. **C-Extension & Wheel Risks:** Many heavy audio packages (`webrtcvad`, `pyaudio`, older `scipy`/`librosa` releases) rely on compiled C/C++ libraries with strict Python ABI dependencies. On Python 3.14, binary wheels for `webrtcvad` are unavailable and fail compilation due to missing MSVC build tools.
2. **Pure Python & Standard Library Power:** Python's standard library provides robust, high-performance audio handling:
   - `wave`: Native RIFF/WAVE header and PCM frame manipulation.
   - `struct`: Lightning-fast C-struct unpacking (`<h` 16-bit signed integers, `<i` 32-bit integers) supporting up to millions of samples per second.
   - `math` & `statistics`: Direct computation of RMS energy, decibel logarithmic scales, variance, and zero-crossing rates.
   - `io.BytesIO`: Zero-copy, in-memory audio buffers.
3. **Installed Libraries Available:**
   - `jiwer` (v3.0.5): Industry-standard Word Error Rate (WER) and Character Error Rate (CER) calculation.
   - `RapidFuzz` (v3.14.6): Fast Levenshtein distance calculations.
   - `pydantic` (v2.14.3): Schema enforcement and validation.
4. **Design Decision:** The Phase 6 Audio Intelligence Engine will be built using standard library audio/mathematical foundations supplemented by `jiwer` and `RapidFuzz`. This eliminates compilation hazards, ensures sub-millisecond execution times, prevents memory leaks, and guarantees 100% deterministic test execution on any Python 3.14+ environment without external C-toolchain requirements.

---

## 4. Missing Noise-Aware Capabilities Required for Phase 6

To satisfy all Phase 6 objectives, the following components must be designed and implemented:

| Capability | Missing Features in Existing Codebase | Technical Solution |
|---|---|---|
| **Audio Metrics** | Peak amplitude, RMS dBFS, clipping sample percentage, zero-crossing rate (ZCR), dynamic range, speech energy vs noise floor. | Implement `app.voice.noise.audio_metrics.AudioMetricsCalculator` analyzing PCM sample frames with exact dBFS and clipping counters. |
| **Noise Classification** | Zero classification. System has no notion of engine rumble, horn spikes, wind turbulence, or background speech. | Implement `app.voice.noise.noise_classifier.HeuristicNoiseClassifier` evaluating spectral balance, peak-to-RMS ratios, ZCR, and temporal variation to classify into 10 explicit categories. |
| **SNR Estimation** | No SNR calculation. | Implement `app.voice.noise.snr_estimator.SNREstimator` using energy-based minimum statistics and voice-activity-gated signal vs. noise floor estimation. Return categorized ratings (GOOD, MODERATE, POOR, VERY_POOR, UNKNOWN). |
| **Voice Activity Detection** | Only monolithic silence detection. Cannot locate speech start/stop or measure pause durations. | Implement `app.voice.noise.vad.EnergyVAD` segmenting audio into frame-level speech vs. silence windows with configurable frame size (20ms) and hangover smoothing. |
| **Adaptive Preprocessing** | Passthrough only. No normalization or filtering. | Implement `app.voice.noise.adaptive_preprocessor.AdaptiveAudioPreprocessor` applying high-pass IIR filtering (to strip engine rumble < 150 Hz), peak-safe RMS normalization (-20 dBFS target), and leading/trailing silence trimming. |
| **Multi-Dimensional Confidence** | Only semantic rule confidence in NLU. | Implement `app.voice.noise.speech_confidence.SpeechConfidenceEvaluator` combining acoustic quality, STT confidence, language detection, intent match, and slot completeness. |
| **Noise-Aware Retry Policy** | Generic "Try again" prompt. | Implement `app.voice.noise.retry_policy.NoiseRetryPolicy` producing actionable, localized suggestions (Tamil, Tanglish, English) based on specific acoustic failure modes (silence, heavy noise, horn spikes, ambiguous amounts). |
| **Benchmarking Engine** | No WER/CER evaluation or noisy audio test set. | Implement `tests.benchmarks.evaluate_transcripts` and `tests.benchmarks.benchmark_stt` measuring WER/CER across clean vs. noisy audio with Unicode normalization. |
| **Frontend Audio Feedback** | No audio quality indicators or localized retry prompts. | Update `frontend/js/voice.js` and `frontend/js/api.js` to surface quality badges (Good/Moderate/Poor) and noise advisories. |

---

## 5. Architectural File Modification & Creation Plan

### 5.1 New Directory Structure: `backend/app/voice/noise/`
- `__init__.py`: Package export interface.
- `audio_metrics.py`: Computes duration, sample rate, channels, RMS, peak, clipping %, silence %, ZCR, noise floor, dynamic range.
- `noise_classifier.py`: Categorizes noise: `CLEAN`, `ENGINE_NOISE`, `TRAFFIC_NOISE`, `HONKING`, `BACKGROUND_SPEECH`, `WIND_NOISE`, `LOW_VOLUME`, `CLIPPING`, `SILENCE`, `UNKNOWN_NOISE`.
- `snr_estimator.py`: Estimates speech and noise levels, computes estimated SNR in dB, categorizes into `GOOD` (>=15 dB), `MODERATE` (8–15 dB), `POOR` (3–8 dB), `VERY_POOR` (<3 dB), or `UNKNOWN`.
- `vad.py`: Energy-based Voice Activity Detection with frame energy histograms, speech boundaries, leading/trailing silence detection, and pause analysis.
- `adaptive_preprocessor.py`: Implements safe, lossless/near-lossless audio transformations (high-pass filtering, normalization, trimming) with fallback to raw audio upon error.
- `speech_confidence.py`: Multidimensional confidence evaluator (`Acoustic`, `STT`, `NLU Intent`, `Entity Extraction`) outputting an explicit action directive (`ACCEPT_FOR_INTERPRETATION`, `ASK_FOR_CLARIFICATION`, `REQUEST_REPEAT`, `REQUIRE_EXPLICIT_CONFIRMATION`, `REJECT_UNUSABLE_AUDIO`).
- `retry_policy.py`: Localized, respectful, concise driver prompts in Tamil, Tanglish, and English preventing infinite retry loops.
- `noise_service.py`: High-level facade orchestrating metrics, classification, SNR, VAD, preprocessing, and confidence.

### 5.2 Modified Existing Files
- `backend/app/voice/schemas.py`: Add `AudioMetricsResult`, `NoiseClassificationResult`, `SNREstimateResult`, `VADResult`, `AdaptivePreprocessingResult`, `SpeechConfidenceResult`, and enrich `STTResponse` & `VoiceTurnResponse`.
- `backend/app/voice/voice_service.py`: Wire `NoiseService` into `transcribe_audio` and `process_voice_turn`.
- `backend/app/routes/voice_routes.py`: Add `POST /api/voice/analyze-audio` endpoint; enrich `/api/voice/chat` and `/api/voice/transcribe` responses with noise intelligence metadata.
- `backend/app/config.py`: Add Phase 6 settings (`AUDIO_NOISE_ANALYSIS_ENABLED`, `AUDIO_SNR_ENABLED`, `AUDIO_VAD_ENABLED`, `AUDIO_ADAPTIVE_PREPROCESSING_ENABLED`, `AUDIO_NOISE_REDUCTION_ENABLED`, `AUDIO_MAX_RETRIES`, `AUDIO_QUALITY_THRESHOLD`).
- `backend/.env.example`: Document new Phase 6 configuration variables.
- `frontend/js/api.js`: Add `analyzeAudio` API method.
- `frontend/js/voice.js`: Add quality badge indicators (Good, Moderate, Poor), noise warnings, and driver retry advisories.

### 5.3 New Benchmark Files: `backend/tests/benchmarks/`
- `__init__.py`
- `dataset_manifest.json`: Structured manifest of synthetic/controlled audio samples across clean, engine noise, traffic, horn, and wind conditions with ground-truth transcripts.
- `synthetic_audio_generator.py`: Generates deterministic test WAV files with exact sinusoidal tones, white/pink noise, harmonic rumble, and synthetic speech envelopes for reproducible testing without proprietary files.
- `evaluate_transcripts.py`: Multilingual WER and CER calculation with Tamil Unicode normalization (NFC) and Tanglish transliteration tolerance.
- `benchmark_stt.py`: Comparative benchmark measuring WER, CER, rejection rate, clarification rate, and processing latency between raw audio and noise-preprocessed audio.

### 5.4 New Automated Test Files: `backend/tests/unit/`
- `test_audio_metrics.py`
- `test_noise_classifier.py`
- `test_snr_estimator.py`
- `test_vad.py`
- `test_adaptive_preprocessor.py`
- `test_speech_confidence.py`
- `test_retry_policy.py`
- `test_noise_service.py`
- `backend/tests/api/test_noise_voice_api.py`

---

## 6. Compatibility & Regression Risk Matrix

| Risk Area | Severity | Mitigation Strategy |
|---|---|---|
| **Python 3.14 C-extension failures** | HIGH | Avoid dependencies requiring MSVC C compilation. Implement core signal processing algorithms in pure Python using `wave`, `struct`, and `math`. |
| **Breaking Phase 1–5 APIs** | CRITICAL | All new fields added to `VoiceTurnResponse` and `STTResponse` must be `Optional` with default values. All 183 existing tests must pass with 0 regressions. |
| **Financial Confirmation Bypass** | CRITICAL | Acoustic confidence evaluation acts as an additional safety gate. It can downgrade confidence or reject audio, but it can **NEVER** bypass driver confirmation for financial transactions. |
| **Audio Processing Latency** | MEDIUM | Keep audio metrics and preprocessing strictly O(N) linear time over PCM samples. Processing a 3-second recording must take < 25 milliseconds. |
| **Distortion from Aggressive Filtering** | MEDIUM | Use conservative high-pass filtering (120–150 Hz cutoff) specifically targeting rumble; apply gentle peak-safe gain adjustments; preserve original audio buffer and revert if processed audio metrics worsen. |

---

## 7. Execution Roadmap

1. **Architecture Audit Documentation:** Write `backend/PHASE_6_ARCHITECTURE_AUDIT.md` (Current step).
2. **Phase 6 Core Noise Package:** Implement `audio_metrics.py`, `noise_classifier.py`, `snr_estimator.py`, `vad.py`, `adaptive_preprocessor.py`, `speech_confidence.py`, `retry_policy.py`, and `noise_service.py`.
3. **Schemas & Configuration:** Update `schemas.py`, `config.py`, and `.env.example`.
4. **Voice Service & Route Integration:** Integrate `NoiseService` into `VoiceService` and add `POST /api/voice/analyze-audio`.
5. **Benchmarking Framework:** Implement synthetic audio generator, dataset manifest, WER/CER evaluator, and comparative STT benchmark.
6. **Frontend Enhancements:** Add non-distracting driver audio quality indicators and localized retry alerts.
7. **Automated Testing & Verification:** Run unit, integration, and API test suites; verify 0 regressions across all 183 existing tests.
8. **Final Deliverables & Git Synchronization:** Write documentation reports, commit with descriptive message, and push to GitHub.
