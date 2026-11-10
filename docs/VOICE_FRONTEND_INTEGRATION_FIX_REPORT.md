# T2T DRIVE — Safe Frontend Voice Integration Fix Report

**Date:** 2026-11-09  
**Engineer:** Senior Full-Stack Integration Engineer  
**Branch:** `main`  
**Provider Mode:** `VOICE_PROVIDER_MODE=mock` (Production default preserved)  
**Safety Status:** 0 Live Gnani Calls Made | 0 Credits Consumed | 0 Production DB Records Modified | 0 Secrets Leaked  

---

## 1. Executive Summary

This report documents the architectural resolution of the three frontend voice integration defects identified during the voice pipeline audit:
1. **Schema Property Mismatch Fixed:** Supported `message`, `reply_text`, and `voice_text` uniformly across both backend schemas and frontend unboxing.
2. **Gnani Timbre Audio Connected:** Replaced default browser `window.speechSynthesis` with native Base64-to-Blob decoding and playback via [`<audio id="ttsAudioPlayer">`](file:///d:/T2T%20DRIVE/frontend/index.html#L316).
3. **Unified Single-Hop Endpoint Connected:** Transitioned the frontend recording flow from fragmented `/api/speech/transcribe` + `/api/agent/message` calls to the unified [`POST /api/voice/chat`](file:///d:/T2T%20DRIVE/backend/app/routes/voice_routes.py#L142) endpoint.

All existing Phase 1–6 and Passenger extension capabilities remain intact. All 13 offline integration tests and 25 regression tests pass with 100% success.

---

## 2. Files Changed and Implementation Overview

| File | Changes Made | Architectural Purpose |
| :--- | :--- | :--- |
| [`frontend/js/api.js`](file:///d:/T2T%20DRIVE/frontend/js/api.js) | Added `ENDPOINTS.voiceChat: "/api/voice/chat"` and implemented `window.API.voiceChat(audio, lang, sessionId, generateTts)`. | Unifies STT, Agent NLU, Confirmation Firewall, and TTS into a single authenticated network request. |
| [`frontend/js/mock-api.js`](file:///d:/T2T%20DRIVE/frontend/js/mock-api.js) | Implemented `generateMockWavBase64()` (8kHz PCM Mono WAV chime) and `MockAPI.voiceChat()`. | Provides 100% faithful offline parity for development, tests, and mock mode without requiring network or API keys. |
| [`frontend/js/voice.js`](file:///d:/T2T%20DRIVE/frontend/js/voice.js) | Updated `processAudioInput()` to call `/api/voice/chat`; added `playTtsAudio()`; added `isProcessingAudio` debounce lock; supported safe fallbacks (`agent_message`, `reply_text`, `message`). | Eliminates fragmented two-hop flow, prevents duplicate submissions, wires native HTML5 audio element, and preserves speech fallback strictly as a labelled fallback. |
| [`backend/app/voice/schemas.py`](file:///d:/T2T%20DRIVE/backend/app/voice/schemas.py) | Added compatibility aliases `reply_text`, `pending_id`, and `entities` to `VoiceTurnResponse`. | Backwards-compatible response contract ensuring zero undefined fields for any client interface. |
| [`backend/app/voice/voice_service.py`](file:///d:/T2T%20DRIVE/backend/app/voice/voice_service.py) | Populated `reply_text`, `pending_id`, and `entities` on `VoiceTurnResponse` inside `process_voice_turn()`. | Exposes pending action and entity details directly in the voice turn response. |
| [`backend/app/agent/service.py`](file:///d:/T2T%20DRIVE/backend/app/agent/service.py) | Added `"reply_text"` alias to `AgentService.process_message()` return payload. | Protects legacy text-only chat endpoints (`/api/agent/message`) from property name mismatches. |
| [`backend/app/routes/voice_routes.py`](file:///d:/T2T%20DRIVE/backend/app/routes/voice_routes.py) | Added alias `@speech_bp.route("/chat", methods=["POST"])`. | Guarantees compatibility whether client requests `/api/voice/chat` or `/api/speech/chat`. |
| [`backend/tests/test_frontend_voice_integration.py`](file:///d:/T2T%20DRIVE/backend/tests/test_frontend_voice_integration.py) | Created 13 automated offline end-to-end integration tests. | Validates all 13 core integration scenarios required by Task 6. |

---

## 3. Verified Request & Response Schema for `POST /api/voice/chat`

### Request Specification
- **URL:** `POST /api/voice/chat` (or alias `POST /api/speech/chat`)
- **Headers:** `Authorization: Bearer <JWT_TOKEN>` (Content-Type header is left unset so browser automatically sets multipart boundary).
- **Multipart Form Fields:**
  - `audio`: Audio file/blob (WAV, MP3, OGG, WebM, M4A, or AAC; maximum 10 MB).
  - `lang` / `language`: (Optional) Language hint (`"tanglish"`, `"ta-IN"`, `"en-IN"`, `"indic-auto"`, default: `"tanglish"`).
  - `session_id`: (Optional) Active session ID string to maintain conversation history across turns.
  - `generate_tts`: (Optional) `"true"` or `"false"` (default: `"true"`).

### Response Specification
Standard JSON envelope returned by `app/utils/responses.py`:
```json
{
  "success": true,
  "data": {
    "session_id": "SESS_8a2d1f930e1b",
    "transcript": "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen.",
    "detected_language": "tanglish",
    "confidence": 0.96,
    "stt_provider": "gnani_prisma",
    "agent_message": "Vanakkam! Understood: Collection ₹1,500, petrol ₹300, Owner payout ₹200. Net take-home ₹1,000. Shall I save this?",
    "reply_text": "Vanakkam! Understood: Collection ₹1,500, petrol ₹300, Owner payout ₹200. Net take-home ₹1,000. Shall I save this?",
    "agent_voice_text": "Vanakkam! Understood: Collection 1500, petrol 300, Owner payout 200. Net take-home 1000. Shall I save this?",
    "intent": "RECORD_EXPENSE",
    "slots": {
      "amount": 300.0,
      "category": "FUEL",
      "vehicle_id": "TN-01-AB-1234"
    },
    "entities": {
      "income": 1500.0,
      "expense": 300.0,
      "owner_payment": 200.0,
      "amount": 300.0,
      "category": "FUEL"
    },
    "pending_id": "PEND_3c81e9f1a024",
    "active_pending_action": {
      "pending_action_id": "PEND_3c81e9f1a024",
      "status": "PENDING",
      "action_type": "ADD_EXPENSE",
      "proposed_data": {
        "amount": "300.0",
        "category": "FUEL",
        "vehicle_id": "TN-01-AB-1234",
        "description": "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen.",
        "transaction_date": "2026-11-09",
        "source": "VOICE_AGENT"
      }
    },
    "next_step": "AWAITING_CONFIRMATION",
    "execution_result": null,
    "tts_audio_base64": "UklGRmQfAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZG...",
    "tts_provider": "gnani_timbre",
    "tts_status": "SUCCESS",
    "error": null,
    "audio_quality": "GOOD",
    "noise_classification": {
      "primary_category": "CABIN_HUM",
      "confidence": 0.94
    },
    "snr_estimate": {
      "snr_db": 24.5,
      "quality": "GOOD"
    }
  },
  "error": null,
  "meta": {
    "timestamp": "2026-11-09T16:45:00.000Z"
  }
}
```

---

## 4. Audio Playback Implementation

### How Audio Playback Works
1. `res.tts_audio_base64` is received directly in the `/api/voice/chat` response.
2. The Base64 string is cleaned of any URI header artifacts and converted into a binary `Uint8Array`.
3. A `new Blob([byteArray], { type: "audio/wav" })` is instantiated.
4. `URL.createObjectURL(blob)` generates a local browser Blob URL.
5. Previous Blob URLs are revoked via `URL.revokeObjectURL(currentTtsBlobUrl)` to prevent client memory leaks.
6. The Blob URL is assigned directly to the native DOM element:
   ```javascript
   ttsAudioPlayer.src = currentTtsBlobUrl;
   ttsAudioPlayer.load();
   ```
7. `ttsAudioPlayer.play()` is invoked.
8. If the client browser restricts autoplay (e.g., initial user gesture restrictions), the promise rejection is caught gracefully without throwing an unhandled exception, and an informative banner alerts the driver: *"Voice reply ready. Tap Play on the audio player to listen."*
9. The telemetry status badge `<span id="ttsStatusPill">` updates to `"GNANI TIMBRE"` with a green pill (`pill-success`).

### Status of Browser-Native TTS Fallback
Browser-native `window.speechSynthesis` is **no longer used as the primary voice mechanism**. It is strictly relegated to an offline/catastrophic network fallback when:
- The backend TTS adapter explicitly fails (`tts_status === "ERROR"`).
- Network drop prevents fetching audio bytes for manual text submissions.
- When invoked, the pill explicitly displays `"BROWSER FALLBACK"` with a warning badge, preventing any illusion that Gnani Timbre was used.

---

## 5. Offline Integration Test Suite Results (13 Scenarios)

The test suite in [`backend/tests/test_frontend_voice_integration.py`](file:///d:/T2T%20DRIVE/backend/tests/test_frontend_voice_integration.py) was executed using `pytest`:

```
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-8.2.2, pluggy-1.7.0
collecting ... collected 13 items

test_scenario_1_tamil_voice_request                         PASSED [  7%]
test_scenario_2_tanglish_voice_request                      PASSED [ 15%]
test_scenario_3_english_voice_request                       PASSED [ 23%]
test_scenario_4_codemixed_voice_request                     PASSED [ 30%]
test_scenario_5_response_compatibility_fields               PASSED [ 38%]
test_scenario_6_audio_format_decodability                   PASSED [ 46%]
test_scenario_7_stt_failure                                 PASSED [ 53%]
test_scenario_8_tts_failure_preserves_text_and_conversation PASSED [ 61%]
test_scenario_9_pending_confirmation_and_ledger_isolation   PASSED [ 69%]
test_scenario_10_user_cancellation                          PASSED [ 76%]
test_scenario_11_unauthenticated_request_rejected           PASSED [ 84%]
test_scenario_12_mongodb_failure                            PASSED [ 92%]
test_scenario_13_repeated_submission_prevention             PASSED [100%]

====================== 13 passed in 3.11s ======================
```

### Scenario Breakdown

1. **Successful Tamil Voice Request:** **PASS** — Sent `stt_tamil.wav`. Returned 200 with Tamil transcript, Tamil reply, and 17 KB Base64 audio.
2. **Successful Tanglish Voice Request:** **PASS** — Sent `stt_tanglish.wav`. Parsed multi-entity collection & expense, returned 200 with Base64 audio.
3. **Successful English Voice Request:** **PASS** — Sent `stt_english.wav`. Parsed income & diesel expense, returned 200 with Base64 audio.
4. **Code-Mixed Voice Request:** **PASS** — Sent `stt_codmix.wav`. Parsed `"Tea and tiffin 60 rupees"`, created pending action for food expense.
5. **Response Compatibility Fields:** **PASS** — Verified `agent_message`, `reply_text`, and `agent_voice_text` are all populated and consistent.
6. **Gnani Audio Decodability:** **PASS** — Decoded `tts_audio_base64` and verified standard `RIFF....WAVE` byte header.
7. **STT Failure:** **PASS** — Handled timeout/error gracefully; `tts_status="SKIPPED"`, `next_step="IDLE"`, 0 pending actions created.
8. **TTS Failure with Conversation Preserved:** **PASS** — Simulated Timbre failure; returned `tts_status="ERROR"`, preserving text reply and 2 MongoDB messages.
9. **Pending Confirmation & Ledger Isolation:** **PASS** — Proposing expense created a pending action with 0 transactions in ledger. Explicit confirmation created exactly 1 ledger transaction.
10. **User Cancellation:** **PASS** — Rejection marked pending action `CANCELLED`. Exactly 0 ledger transactions created.
11. **Authentication Failure:** **PASS** — Request without token rejected with 401 UNAUTHORIZED.
12. **MongoDB Failure:** **PASS** — Simulated database error caught cleanly; returned 500 error without reporting fake success.
13. **Repeated Submission Prevention:** **PASS** — Duplicate confirmation attempts returned the existing confirmed result idempotently without duplicate ledger entries.

---

## 6. Financial Confirmation & Regression Testing

Executed existing unit and API test suites:
- `backend/tests/unit/test_voice_service.py`: 5 passed
- `backend/tests/api/test_voice_api.py`: 11 passed
- `backend/tests/api/test_agent_api.py`: 9 passed
- `backend/tests/test_frontend_voice_integration.py`: 13 passed

**Total Tests Executed:** 38 passed | 0 failed | 0 skipped.

---

## 7. Final Acceptance Criteria Evaluation

| # | Acceptance Criterion | Evaluation | Verification Evidence |
| :---: | :--- | :---: | :--- |
| **1** | **Record a driver's voice** | **PASS** | `startRecording()` captures mic audio via `MediaRecorder` into a 16-bit PCM WAV blob. |
| **2** | **Send recording to `/api/voice/chat`** | **PASS** | `processAudioInput()` dispatches multipart upload directly to `window.T2T_CONFIG.ENDPOINTS.voiceChat`. |
| **3** | **Receive backend's response** | **PASS** | Single-hop response unboxes `VoiceTurnResponse` payload with all compatibility aliases. |
| **4** | **Display recognized text and assistant response** | **PASS** | Populates `liveTranscriptBox`, adds user bubble, and appends assistant bubble (`agent_message || reply_text`). |
| **5** | **Play audio returned by backend's TTS service** | **PASS** | `playTtsAudio()` decodes `tts_audio_base64` into a Blob URL and plays via `<audio id="ttsAudioPlayer">`. |
| **6** | **Preserve conversation history in MongoDB** | **PASS** | `db.conversation_messages` stores both `DRIVER` and `AGENT` records; retrievable across restarts. |
| **7** | **Require explicit confirmation before financial ledger mutations** | **PASS** | Speech creates `PendingAction` only; ledger mutation strictly requires tactile/voice confirm. |

---

## 8. Remaining Limitations

1. **Remote Gnani Prisma Production Gateway:** As documented in [`docs/PRISMA_SSL_FAILURE_INVESTIGATION.md`](file:///d:/T2T%20DRIVE/docs/PRISMA_SSL_FAILURE_INVESTIGATION.md), the remote live endpoint `https://api.vachana.ai/stt/v3` forcibly resets TCP connections (`ConnectionResetError: 10054`) on server-side ASR inference times exceeding ~30 seconds. The application correctly handles this offline with mocks (`VOICE_PROVIDER_MODE=mock`), and standard TLS with 60s client timeout is ready for when the upstream Gnani server latency stabilizes.
2. **Autoplay Restrictions on Inactive Browsers:** Web browsers (Chrome, Edge, Safari) prohibit audio autoplay until the user interacts with the page. Since the driver initiates voice interaction by clicking the PTT button, autoplay permissions are granted in standard usage; if blocked, the UI gracefully prompts the driver with a play button.
