# T2T-DRIVE — VOICE RELIABILITY & ACOUSTIC INTELLIGENCE REPORT

**Project:** T2T-DRIVE (Noise-Aware Multilingual Voice Co-Pilot)  
**Evaluation Scope:** Phase 4 & Phase 6 Audio Preprocessing, Environmental Noise Resilience, Multilingual NLU, and Speech Synthesis  
**Date:** November 10, 2026  
**Auditor Status:** Automated Acoustic Benchmark & Integration Verification  

---

## 1. Acoustic Intelligence & Noise Pipeline Architecture

Auto-rickshaws operate in severe acoustic environments: single-cylinder engine rumble (55Hz–165Hz), wind buffeting, high-frequency horn blasts, and ambient street noise. The voice processing pipeline implements a multi-stage pre-flight defense:

```
[ Incoming Audio Byte Stream (WAV / WebM) ]
                     │
                     ▼
       1. Audio Inspection & Validation
          • Format verification, duration checks (0.2s–60s)
          • RMS amplitude calculation & pure silence detection
                     │
                     ▼
       2. Acoustic Metric & SNR Analysis
          • Zero-Crossing Rate (ZCR), Spectral Energy, Peak dBFS
          • Signal-to-Noise Ratio (SNR) estimation
          • Noise Classification: Engine, Traffic, Honking, Wind, Silence
                     │
                     ▼
       3. Adaptive Audio Preprocessing
          • High-pass IIR filtering (cutoff 120 Hz) for engine rumble
          • Peak-safe dynamic range normalization for low-volume speech
          • Leading and trailing silence trimming
                     │
                     ▼
       4. Speech Activity & Confidence Gate
          • Rejects pure silence / muted mic before network calls
          • Emits retry advisory prompts if audio is degraded
                     │
                     ▼
       5. Gnani Prisma STT v3.0 (WAV Mono 16kHz)
                     │
                     ▼
       6. Multilingual NLU & Confirmation Firewall
          • Extracts Tamil, Tanglish, and English intents & slots
          • Clarifies missing amounts (AWAITING_SLOT)
          • Requires explicit confirmation (AWAITING_CONFIRMATION)
                     │
                     ▼
       7. Gnani Timbre TTS Speech Synthesis (Kaveri / Nalini)
```

---

## 2. Multilingual Speech Evaluation Benchmarks

The voice evaluation suite was executed against calibrated speech audio fixtures and synthetic acoustic scenarios:

### Test Case 1: Clean Tamil Speech (`stt_tamil_16k.wav`)
- **Utterance:** *"டீசல் 400 போட்டேன்"*
- **Language Detected:** `ta-IN` (Tamil)
- **Extracted Intent:** `RECORD_EXPENSE`
- **Extracted Slots:** Category: `FUEL`, Amount: `₹400.00`
- **Confirmation Gate:** Successfully generated proposal `PEND_...`, transitioned to `AWAITING_CONFIRMATION`
- **TTS Synthesis:** Timbre Kaveri voice synthesis executed in `ta-IN`
- **Turn Latency:** < 5000ms

### Test Case 2: Tanglish Compound Multi-Action Utterance (`T2T_Tanglish_Test_Audio.wav`)
- **Utterance:** *"இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."*
- **Language Detected:** `tanglish`
- **Extracted Intent:** `RECORD_BATCH_TRANSACTIONS`
- **Extracted Batch Items:**
  1. `FARE`: `₹1500.00` (Income)
  2. `FUEL`: `₹300.00` (Expense)
  3. `OWNER_RENT`: `₹200.00` (Owner Settlement)
- **Mathematical Consistency:** Total Income (1500) - Expense (300) - Owner (200) = Net Balance (1000)
- **Confirmation Gate:** Proposes single atomic batch, preserving financial precision without writes.

### Test Case 3: English Driver Speech (`stt_english.wav`)
- **Utterance:** *"filled diesel 400"*
- **Language Detected:** `en-IN` (English)
- **Extracted Intent:** `RECORD_EXPENSE`
- **Extracted Slots:** Category: `FUEL`, Amount: `₹400.00`
- **Verification:** Successfully parsed into English confirmation prompt.

### Test Case 4: Code-Mixed Tamil-English (`stt_codmix.wav`)
- **Utterance:** *"petrol 300 potten tea 30"*
- **Language Detected:** `tanglish`
- **Extracted Intent:** `RECORD_BATCH_TRANSACTIONS`
- **Extracted Slots:** `FUEL: ₹300.00`, `FOOD: ₹30.00`
- **Verification:** Both items correctly classified with distinct categories.

---

## 3. Acoustic Resilience & Preprocessing Verification

### 3.1 Severe Auto-Rickshaw Engine Rumble Resilience
- **Condition:** Synthesized 2.0s vehicle engine vibration (55Hz, 110Hz, 165Hz harmonics) mixed at 12 dB SNR.
- **Classification Result:** Primary category identified as `ENGINE_NOISE`.
- **Pre-flight Transformation:** Applied high-pass IIR filtering (`HIGH_PASS_FILTER_120HZ`).
- **Outcome:** Engine rumble attenuated without clipping, preserving speech formants.

### 3.2 Low-Volume Speech Normalization
- **Condition:** Low-amplitude driver voice (peak amplitude < 900 / 32767, RMS dBFS < -32.0).
- **Classification Result:** Primary category identified as `LOW_VOLUME`.
- **Pre-flight Transformation:** Applied peak-safe RMS normalization (`PEAK_SAFE_NORMALIZATION`).
- **Outcome:** Audio amplitude scaled safely to target operating range without introducing digital clipping distortion (< 0.1% clipping).

### 3.3 Silence Detection & Pre-Flight Safeguards
- **Condition:** Muted microphone or pure acoustic silence (RMS < 50.0).
- **Classification Result:** Primary category identified as `SILENCE` / `UNUSABLE`.
- **Safety Action:** STT and LLM processing skipped entirely.
- **Agent Response:** Returns `IDLE` state with advisory prompt: *"Voice could not be recognized. Please try speaking again."*
- **Financial Protection:** Zero proposals created, zero database writes.

### 3.4 Ambiguous Amount Clarification
- **Utterance:** *"diesel potten"* (missing amount).
- **NLU Parsing:** Intent `RECORD_EXPENSE`, category `FUEL`, missing slot `['amount']`.
- **Conversational Action:** Rather than failing or recording zero rupees, the agent enters `AWAITING_SLOT` and speaks a natural clarification prompt:
  - Tamil: *"டீசல் செலவு எவ்வளவு ரூபாய் என்று சொல்லுங்கள்?"*
  - Tanglish: *"Evvalavu roobai diesel pottirukeenga?"*
  - English: *"Please specify the amount for Diesel."*

### 3.5 Confirmation Firewall Cancellation
- **Utterance:** *"vendaam cancel pannu"* during active confirmation.
- **Resolution:** Tested negative terms (`vendaam`, `cancel pannu`) prioritized over affirmative terms (`pannu`).
- **Result:** Successfully transitions pending action to `CANCELLED` with **zero writes** to MongoDB transactions.

---

## 4. Voice Evaluation Suite Execution Evidence

The complete 10-point voice evaluation suite was executed via `pytest backend/tests/integration/test_voice_evaluation_suite.py`:

```
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_01_clean_tamil_speech_evaluation PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_02_tanglish_multi_action_speech_evaluation PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_03_english_speech_evaluation PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_04_code_mixed_speech_evaluation PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_05_acoustic_engine_noise_resilience PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_06_low_volume_speech_normalization PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_07_silence_detection_and_safeguards PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_08_ambiguous_amount_triggers_clarification PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_09_explicit_confirmation_firewall PASSED
backend/tests/integration/test_voice_evaluation_suite.py::TestVoiceEvaluationSuite::test_10_tts_synthesis_and_language_selection PASSED

======================== 10 passed in 4.53s ========================
```
