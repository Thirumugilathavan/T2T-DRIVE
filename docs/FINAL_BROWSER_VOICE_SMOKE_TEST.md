# T2T DRIVE — Final Browser Smoke Test Report

**Execution Mode:** Local Browser Automated Smoke Test (Google Chrome Headless + CDP)  
**Date & Timestamp:** 2026-11-09T17:15:42Z (22:45:42 IST)  
**Browser Engine:** Google Chrome `156.0.8078.80` (Chromium x86_64)  
**Backend Port:** `http://127.0.0.1:5005` (Werkzeug Test Server)  
**Database:** Disposable In-Memory `mongomock` (`t2t_drive_test`)  
**Live Gnani API Calls:** 0 (Zero credits consumed)  
**Secrets Exposed:** 0 (Strictly zero credentials logged or displayed)  
**Overall Result:** **ALL 5 SUITES PASSED (100% PASS RATE)**

---

## Executive Summary

Following the frontend voice integration fix (which unified the voice flow onto `/api/voice/chat`, bound synthesized audio to the native `<audio id="ttsAudioPlayer">` element, and harmonized payload field mappings), an end-to-end browser smoke test was executed. 

The test ran in headless Google Chrome using the Chrome DevTools Protocol (CDP) over WebSockets, interacting with the real DOM, Web Audio API, `MediaRecorder`, HTML5 Audio elements, and a live Flask backend instance wired to a disposable `mongomock` database.

| Test ID | Test Category | Target Component | Status | Key Empirical Observation |
|---|---|---|---|---|
| **TEST 1** | Microphone Recording & Format Inspection | `MediaRecorder` & `AudioValidator` | **PASS** | Native MIME: `audio/webm;codecs=opus`; Magic bytes: `1A 45 DF A3` (EBML/WebM); Accepted by backend validator. |
| **TEST 2** | Complete Voice Turn Interaction | `/api/voice/chat`, UI & Audio Player | **PASS** | Recognized transcript rendered in `#liveTranscriptBox`, assistant response in chat stream & preview, Blob URL bound to `#ttsAudioPlayer`. |
| **TEST 3** | Database Persistence & Isolation | `conversation_sessions`, `messages` | **PASS** | DRIVER & AGENT messages stored; 100% preserved after simulated restart; unauthorized driver query blocked. |
| **TEST 4** | Financial Safety & Firewall | `PendingActionService` & Ledger | **PASS** | Zero ledger mutation prior to confirmation; exactly 1 transaction created upon explicit confirm; zero upon cancel. |
| **TEST 5** | Error Handling & Autoplay Resilience | Client & Service Exception Handlers | **PASS** | Handled microphone denial (`NotAllowedError`), empty audio rejection, STT failure fallback, TTS failure fallback, and autoplay policy. |

---

## Detailed Test Results

### Test 1: Microphone Recording & Audio Format Inspection

* **Target:** Browser microphone access via `navigator.mediaDevices.getUserMedia` and native `MediaRecorder` capture.
* **Result:** **PASS**
* **Technical Findings:**
  1. **Microphone Permission:** Successfully acquired via fake audio capture stream (`--use-fake-ui-for-media-stream`, `--use-fake-device-for-media-stream`).
  2. **Browser Native Recording MIME:** Modern Chromium **does not record in WAV by default**. Its native container is:
     ```
     audio/webm;codecs=opus
     ```
     `MediaRecorder.isTypeSupported('audio/wav')` evaluated to `false`.
  3. **Binary Magic Bytes Signature:**
     - **Hex Dump (first 16 bytes):** `1a 45 df a3 9f 42 86 81 01 42 f7 81 01 42 f2 81`
     - **ASCII Representation:** `.E...B...B...B..`
     - **Detected Signature:** Standard EBML Header (`1A 45 DF A3`), confirming valid WebM/Matroska container.
  4. **Backend Acceptance:** `AudioValidator.validate_bytes()` was evaluated against the captured container format. It successfully matched the `b"\x1a\x45\xdf\xa3"` magic signature to format `"webm"`, satisfying all upload criteria without rejection.

---

### Test 2: Complete Mock Voice Turn (Tamil STT → AI Agent → Timbre TTS)

* **Target:** End-to-end voice turn submission via `window.VoiceModule.processAudioInput(file)` triggering `POST /api/voice/chat`.
* **Audio Input:** `stt_tamil.wav` (Colloquial spoken Tamil recorded clip).
* **Result:** **PASS**
* **Verification Steps & Observations:**
  1. **Upload & STT Recognition:** Spoken input recognized as:
     ```
     இன்னைக்கு நான் ஐநூறு ரூபாய் சம்பாதிச்சேன்
     ```
  2. **UI Rendering:**
     - `#liveTranscriptBox` dynamically populated with the recognized Tamil transcript.
     - `#detectedLangText` correctly indicated `ta-IN`.
     - `#chatStreamBox` updated with user speech bubble containing the transcription.
  3. **Conversational Agent Processing:** LangGraph agent processed the Tamil income intent (`RECORD_INCOME`), generated multi-turn response text, and rendered an AI speech bubble into the stream.
  4. **Audio Synthesis & Player Binding:**
     - Mock Timbre synthesized PCM WAV chime base64.
     - Frontend `playTtsAudio()` converted the base64 string into a Blob Object URL (`blob:http://127.0.0.1:5005/...`).
     - URL was directly assigned to `<audio id="ttsAudioPlayer">`.
     - `#ttsStatusPill` updated to `GNANI TIMBRE`.
     - `#ttsTextPreview` mirrored the assistant's response.

---

### Test 3: MongoDB Persistence in Disposable Database

* **Target:** `conversation_sessions` and `conversation_messages` collections in `mongomock`.
* **Result:** **PASS**
* **Verification Steps & Observations:**
  1. **Driver & Agent Storage:**
     - `DRIVER` message count in DB: `1`
     - `AGENT` message count in DB: `1`
     - Session ID: `SESS_19676836917e9ca1` associated with driver `DRV_1001`.
  2. **History Retrieval Across Simulated Restart:**
     - A completely new instance of `AgentService` was initialized connecting to the existing database.
     - Queried session messages for session `SESS_19676836917e9ca1`.
     - All 2 messages were retrieved intact in strict chronological order with complete role metadata.
  3. **Driver Ownership Isolation:**
     - An unauthorized driver identifier (`OTHER_DRIVER_HACKER`) attempted to retrieve the messages for `SESS_19676836917e9ca1`.
     - Request was blocked with `PermissionError` (HTTP 403 equivalent), verifying session isolation.

---

### Test 4: Financial Safety (Confirmation Firewall & Zero Mutation)

* **Target:** Strict enforcement of the mandatory confirmation boundary on financial entries.
* **Result:** **PASS**
* **Verification Steps & Observations:**
  1. **Initial Ledger Count:** `initial_tx = 0`.
  2. **Expense Proposal:**
     - Tanglish voice clip submitted: `"Diesel 350 rupees potten"`.
     - Intent classified as `RECORD_EXPENSE` (Fuel, ₹350.00).
     - `#transactionConfirmContainer` card automatically became visible in the browser DOM (`display: block` / unhidden).
     - `#chipExpenseVal` dynamically rendered the expense value.
  3. **Zero Mutation Prior to Confirmation:**
     - Database ledger queried: `tx_after_propose = 0`.
     - Verified: **Zero financial mutations occurred prior to explicit user confirmation.**
  4. **Explicit Confirmation Turn:**
     - Invoked `window.API.confirm(pending_id, true)`.
     - Status changed from `PENDING` to `CONFIRMED`.
     - Single atomic transaction recorded: `TXN_889a9928d2682a18` (`INCOME / EXPENSE 350.00`).
     - Database ledger queried: `tx_after_confirm = 1` (mutation: `+1`).
  5. **Explicit Cancellation Turn:**
     - Second expense clip submitted, creating pending action `PEND_07c5dd44af8a96d1`.
     - Invoked `window.API.confirm(pending_id_2, false)` (explicit rejection).
     - Status changed to `CANCELLED`.
     - Database ledger queried: `tx_after_cancel = 1` (mutation: `+0`).
     - Verified: **Zero transactions written on cancellation.**

---

### Test 5: Error Handling & Edge Cases

* **Target:** System resilience against browser hardware denial, corrupt input, and upstream service outages.
* **Result:** **PASS**
* **Verification Steps & Observations:**
  1. **Microphone Denial (`NotAllowedError`):**
     - Simulated `DOMException("Permission denied", "NotAllowedError")`.
     - Frontend exception catch block cleanly surfaced informative feedback without crashing the application state.
  2. **Empty / Corrupt Audio:**
     - Passed 0-byte buffer to `AudioValidator`.
     - Rejected with `is_valid: False`, error: `"Audio file is empty"`.
  3. **STT Outage Handling:**
     - Simulated upstream STT gateway timeout / network drop.
     - Handled gracefully: `transcript == ""` and `tts_status == "SKIPPED"`, without throwing 500 errors.
  4. **TTS Outage Handling:**
     - Simulated upstream TTS service unavailability.
     - Backend returned `tts_status == "ERROR"` while preserving the complete textual `agent_message`.
     - Frontend rendered the text reply in the chat stream, displayed a warning pill (`TTS UNAVAILABLE`), and suppressed player errors.
  5. **Browser Autoplay Restrictions:**
     - Verified `<audio>` element handles autoplay policy rejection (`playPromise.catch()`) by alerting the driver to tap play manually rather than breaking execution.

---

## Live Gnani Status & Architectural Transparency

> [!IMPORTANT]
> **Live Prisma STT Upstream Status:**
> In accordance with project safeguards:
> - **Zero live Gnani API requests** were made during this browser test suite.
> - **Zero live API credits** were consumed.
> - The live Gnani Prisma STT upstream connection reset issue (`UNEXPECTED_EOF_WHILE_READING` / `ECONNRESET`) remains an unresolved external service/gateway issue pending upstream resolution with Gnani support.
> - The production default setting remains safely in `VOICE_PROVIDER_MODE=mock`.

---

## Artifacts Generated

1. **Test Runner:** [`backend/tests/run_final_browser_smoke_test.py`](file:///d:/T2T%20DRIVE/backend/tests/run_final_browser_smoke_test.py)
2. **Machine-Readable Report:** [`backend/tests/final_browser_smoke_report.json`](file:///d:/T2T%20DRIVE/backend/tests/final_browser_smoke_report.json)
3. **Screenshots:**
   - Idle State: [`backend/tests/audio_preview/browser_smoke_01_idle.png`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/browser_smoke_01_idle.png)
   - Completed Voice Turn: [`backend/tests/audio_preview/browser_smoke_02_voice_turn.png`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/browser_smoke_02_voice_turn.png)
   - Confirmation Firewall Card: [`backend/tests/audio_preview/browser_smoke_03_confirmation_card.png`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/browser_smoke_03_confirmation_card.png)
