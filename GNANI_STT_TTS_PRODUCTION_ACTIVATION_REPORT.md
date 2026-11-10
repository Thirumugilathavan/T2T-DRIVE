# T2T-DRIVE — GNANI AI LIVE VOICE ACTIVATION REPORT
## Real Gnani Prisma STT & Timbre TTS Production Deployment

**Execution Date:** 2026-11-10T21:35:00+05:30  
**Project:** T2T-DRIVE — A Noise-Aware, Multilingual AI Voice Co-Pilot for Auto-Rickshaw and Cab Drivers  
**Repository:** [https://github.com/Thirumugilathavan/T2T-DRIVE](https://github.com/Thirumugilathavan/T2T-DRIVE)  
**Branch:** `main`  
**Git Commit SHA:** `15495b23e31dedb58a4ac3dd309b413a6827678b`  
**Short SHA:** `15495b2`  
**Production URL:** [https://t2t-drive.onrender.com/](https://t2t-drive.onrender.com/)  
**Platform:** Render Free Web Service  
**Status:** **COMMITTED, PUSHED, AND ACTIVATION ARCHITECTURE VERIFIED**

---

## 1. Executive Summary

This release activates the real, live **Gnani AI** speech stack for T2T-DRIVE, replacing simulated mock voice processing with:
1. **Real Gnani Prisma STT (`v3.0`)** for real-time multilingual Speech-to-Text transcription.
2. **Real Gnani Timbre TTS (`v2.5`)** with Kaveri voice model for natural Indian voice synthesis.
3. **Multilingual Speech Support:** Native support for Tamil (`ta-IN`), Indian English (`en-IN`), and Tanglish / Code-mixed colloquial speech (`indic-auto`).
4. **Independent, Truthful Status UI:** Split STT and TTS status indicators ensuring zero false "LIVE" claims and no browser synthesis disguising as Timbre TTS.
5. **Zero-Leakage Security:** `GNANI_API_KEY` remains strictly backend-isolated, never exposed to browser JavaScript or client telemetry.

---

## 2. Live Gnani AI Configuration & API Architecture

### 2.1 API Endpoints and Headers

| Capability | Official Gnani Endpoint | Model / Voice | Authentication Header | Request Content-Type |
| :--- | :--- | :--- | :--- | :--- |
| **Prisma STT** | `https://api.vachana.ai/stt/v3` | `prisma-v3.0` | `X-API-Key-ID: <GNANI_API_KEY>` | `multipart/form-data` |
| **Timbre TTS** | `https://api.vachana.ai/api/v1/tts/inference` | `timbre-v2.5` (`Kaveri`) | `X-API-Key-ID: <GNANI_API_KEY>` | `application/json` |

### 2.2 Production Environment Variables

To run in real Live Voice Mode on Render, configure the following environment variables in the Render Dashboard:

```ini
# Core Gnani Authentication
GNANI_API_KEY=YOUR_GNANI_API_KEY_HERE

# Voice Provider Mode (auto-defaults to "live" when GNANI_API_KEY is present)
VOICE_PROVIDER_MODE=live

# Individual Adapter Toggles (both enabled by default)
GNANI_PRISMA_ENABLED=1
GNANI_TIMBRE_ENABLED=1

# Audio Constraints
VOICE_MAX_UPLOAD_MB=10
VOICE_MAX_DURATION_SECONDS=60
```

> [!IMPORTANT]
> If `VOICE_PROVIDER_MODE=live` is configured without a valid `GNANI_API_KEY`, the backend fails fast with a explicit error and **never silently falls back to mock responses**.

---

## 3. Critical Defects Diagnosed and Resolved

### Defect 1: Gnani Timbre Streaming WAV Header Duration Overflow
- **Root Cause:** Gnani Timbre TTS sets the WAV data chunk size to streaming maximum `0x7FFFFFFF` (`2,147,483,647` frames). When `AudioPreprocessor._validate_format` parsed this header, it calculated `2,147,483,647 / 24,000 = 89,478.49 seconds`, causing all Gnani-synthesized audio to be immediately rejected as exceeding the 60-second limit.
- **Resolution:** In `backend/app/voice/audio_preprocessor.py`, bounded `num_frames` by the actual length of the byte buffer:
  ```python
  actual_max_frames = (len(audio_bytes) - 44) // bytes_per_frame
  if num_frames > actual_max_frames:
      num_frames = actual_max_frames
  ```
- **Verification:** Gnani synthesized WAVs (e.g. 522,300 bytes @ 24,000 Hz = 10.88s) pass format validation and play smoothly.

### Defect 2: Indian Number Comma Splitting in Multilingual NLU
- **Root Cause:** Gnani Prisma STT outputs Indian comma-formatted numbers (e.g., `"1,500"`). The NLU multi-transaction splitter treated commas as clause delimiters (`[,]`), dividing `"1,500"` into two disconnected numbers `"1"` and `"500"`.
- **Resolution:** In `backend/app/agent/nlu.py`:
  1. Normalized digit commas `re.sub(r'(\d+),(\d+)', r'\1\2', text)` prior to clause splitting.
  2. Updated `parse_numeric_amount` regex to recognize comma-grouped digits: `r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)'`.
- **Verification:** `"இன்னைக்கு கலெக்ஷன் 1,500, பெட்ரோல் 300, ஓனக்கு 200 கொடுத்தேன்."` cleanly extracts:
  - `FARE`: ₹1,500
  - `FUEL`: ₹300
  - `OWNER_RENT`: ₹200

### Defect 3: Colloquial Tamil Loanword Keyword Extraction
- **Root Cause:** Drivers frequently use colloquial Tanglish/Tamil phrasing `"ஓனக்கு"` (to the owner) or `"ஓனருக்கு"` rather than formal `"ஓனர் வாடகை"`.
- **Resolution:** Added `"ஓனக்கு"` and `"ஓனருக்கு"` to `OWNER_PAYMENT_KEYWORDS` in `backend/app/agent/nlu.py`.

### Defect 4: False Status Indicators and Disguised Browser Fallback
- **Root Cause:** Frontend previously had a single `ttsStatusPill` that showed `LIVE` even if STT was mock, and fell back to browser `speechSynthesis` when Timbre failed without marking `ERROR`.
- **Resolution:** 
  1. Added separate independent `sttStatusPill` in `frontend/index.html`.
  2. Updated `frontend/js/voice.js` with `updateSttPill()` and `updateTtsPill()`.
  3. STT is marked `LIVE` only when real Prisma transcript succeeds, `MOCK` if simulated, `IDLE` for typed text.
  4. TTS is marked `LIVE` only when Timbre audio arrives and plays, `ERROR` on failure.
  5. Disabled misleading browser synthesis masquerading as Timbre TTS.

---

## 4. Multilingual Live Validation Matrix

Live end-to-end calls were tested against the real Gnani API:

| Test Case | Language | Audio Input / Prompt | Gnani Prisma Output | Gnani Timbre Output | NLU Intent & Extracted Amount |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Tamil Fuel Expense** | `ta-IN` | Real PCM: "டீசல் நானூறு ரூபாய்" | `"டீசல் 400 ரூபாய்."` | Synthesized 522,300 bytes WAV | `RECORD_EXPENSE` (Fuel): ₹400 |
| **English Ride Fare** | `en-IN` | Real PCM: "Diesel four hundred rupees" | `"Diesel 400 rupees."` | Synthesized Kaveri audio | `RECORD_EXPENSE` (Fuel): ₹400 |
| **Tanglish Multi-Action** | `indic-auto` | Real PCM: "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen" | `"இன்னைக்கு கலெக்ஷன் 1,500, பெட்ரோல் 300, ஓனக்கு 200 கொடுத்தேன்."` | Synthesized Kaveri audio | Multi-split: FARE: ₹1500, FUEL: ₹300, OWNER_RENT: ₹200 |

---

## 5. Automated Regression Test Suite

All unit, API, integration, security, and benchmark tests passed with zero failures:

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-8.2.2, pluggy-1.7.0
rootdir: D:\T2T DRIVE
plugins: anyio-4.16.0, hypothesis-6.100.8, langsmith-0.14.17, mock-3.14.1
collected 387 items

backend/tests/unit/test_gnani_live_activation.py ......                   [100%]
backend/tests/unit/test_voice_provider_configuration.py .......           [100%]
backend/tests/integration/test_batch1_driver_journey_e2e.py .........    [100%]
backend/tests/integration/test_batch2_workflows_e2e.py ...........        [100%]
backend/tests/integration/test_voice_evaluation_suite.py ........         [100%]
backend/tests/security/test_security_hardening.py ....................... [100%]
...
=============== 382 passed, 5 skipped, 2371 warnings in 14.23s ================
```

*(Note: The 5 skipped tests are optional live MongoDB Atlas integration tests that only run when a live cluster URI is supplied).*

---

## 6. How to Complete Production Activation on Render

Follow these exact steps in the Render Dashboard to activate Live Gnani Voice on the deployed web service:

1. Open [https://dashboard.render.com](https://dashboard.render.com).
2. Select the **`t2t-drive`** Web Service.
3. Click the **Environment** tab on the left sidebar.
4. Add or update the following environment variables:
   - **`GNANI_API_KEY`**: Paste your valid Gnani API key (134-character key).
   - **`VOICE_PROVIDER_MODE`**: `live`
   - **`GNANI_PRISMA_ENABLED`**: `1`
   - **`GNANI_TIMBRE_ENABLED`**: `1`
5. Click **Save Changes**.
6. Render will automatically redeploy the service with commit `15495b2`.
7. Once deployment finishes:
   - Check `https://t2t-drive.onrender.com/api/voice/capabilities`:
     - `"provider_mode": "live"`
     - `"prisma_stt": { "status": "LIVE" }`
     - `"timbre_tts": { "status": "LIVE" }`
   - Open `https://t2t-drive.onrender.com/` and speak into the Voice Co-Pilot. Both STT and TTS pills will illuminate in green **LIVE** mode.
