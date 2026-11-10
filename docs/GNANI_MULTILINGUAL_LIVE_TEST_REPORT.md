# T2T DRIVE — Gnani AI Multilingual Live Integration Test Report

**Execution Date:** 2026-11-09 20:58:22  
**Final Status:** `STAGE 1 INCOMPLETE / HALTED`  
**Total Live API Calls:** `2 / 2` (Stage 1 hard budget strictly enforced; 0 calls made to Stage 2)  

---

## 1. Stage 1 Execution Summary

| Request | Service | Endpoint | HTTP Status | Latency | Outcome |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **Request 1** | **Gnani Timbre TTS** | `POST /api/v1/tts/inference` | **200 OK** | **17.3s** | **SUCCESS** &bull; Audio generated & saved |
| **Request 2** | **Gnani Prisma STT** | `POST /stt/v3` | **Network Error** | — | **FAILED** &bull; SSL Unexpected EOF |

---

## 2. Request 1 Results — Tamil Speech Synthesis (Timbre v2.5)

- **Input Text:** `உங்கள் வருமானம் ஐநூறு ரூபாய்.`
- **Voice / Model:** `Kaveri` / `timbre-v2.5`
- **Language Locale:** `ta-IN`
- **HTTP Status:** `200 OK`
- **Latency:** `17,317 ms`
- **Output Audio Path:** [`backend/tests/audio_preview/tts_tamil.wav`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/tts_tamil.wav)
- **Audio Verification:**
  - **Container / Encoding:** Linear PCM WAV (16-bit)
  - **Sample Rate:** `24,000 Hz`
  - **Channels:** `1 (Mono)`
  - **Duration:** `1.76 seconds`
  - **File Size:** `84,524 bytes`
  - **Playback Status:** Generated, playable audio file.
- **Credit / Request Headers:**
  - `x-request-id`: Not exposed by provider response.
  - Credit balances / headers: Not returned in HTTP response headers.

---

## 3. Request 2 Results — Tamil Speech Recognition (Prisma v3.0)

- **Input Audio File:** [`backend/tests/test_audio/stt_tamil.wav`](file:///d:/T2T%20DRIVE/backend/tests/test_audio/stt_tamil.wav)
- **Input Spoken Phrase:** `இன்னைக்கு நான் ஐநூறு ரூபாய் சம்பாதிச்சேன்.`
- **Target Language:** `ta-IN`
- **Target Format:** `codemix`
- **Model:** `prisma-v3.0`
- **Outcome:** **FAILED (Network/TLS Protocol Error)**
- **Raw Exception:** `[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1082)`
- **Failure Analysis:**
  The TLS connection to `https://api.vachana.ai/stt/v3` was abruptly terminated by the server before the HTTP handshake/response was delivered. This is typically caused by:
  1. A TLS/cipher handshake termination under Windows OpenSSL 3.x with strict EOF checking.
  2. The endpoint expecting specific TLS session parameters or a different sub-path / port for REST multipart STT.
  3. Server-side connection reset during large multipart stream ingestion.

---

## 4. Stage 1 Gate Outcome

- **Gate Status:** **HALTED**
- Under strict safety instructions:
  > *"If either request fails, stop immediately. Do not execute Stage 2 after a failed or incomplete Stage 1. Do not retry failed requests."*
- **Stage 2 Execution:** **NOT EXECUTED**. Zero requests were consumed on Stage 2.

---

## 5. Local Audio Playback Preview (Section 9)

An interactive HTML audio player has been generated:
- **Local Preview Webpage:** [`backend/tests/audio_preview/index.html`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/index.html)
- **Direct Audio File:** [`backend/tests/audio_preview/tts_tamil.wav`](file:///d:/T2T%20DRIVE/backend/tests/audio_preview/tts_tamil.wav)
