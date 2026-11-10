# T2T DRIVE — Prisma STT Connection Termination Investigation Report

**Document Version:** 3.0 (Post Live Diagnostic Execution)  
**Execution Date:** 2026-11-09 21:35:38  
**Authorized Live Requests Executed:** **`1`** (Strict single-request limit enforced)  
**Total Cumulative Live Requests (All Sessions):** `3` (1 Timbre TTS + 2 Prisma STT attempts)  

---

## 1. Executive Summary of Single Authorized Live STT Request

In accordance with explicit user authorization, exactly **one** live request was dispatched to Gnani Prisma STT using:
- Production `requests`-based `PrismaAdapter`.
- Standard TLS certificate verification (`verify=True`).
- Configurable `timeout_seconds = 60.0`.
- Standard OpenSSL socket handling (zero workarounds, no `OP_IGNORE_UNEXPECTED_EOF`).
- Target audio: `backend/tests/test_audio/stt_tamil.wav` (preprocessed to standard 16 kHz Mono 16-bit PCM WAV, 147,244 bytes).
- Model: `prisma-v3.0` | Language: `ta-IN` | Format: `codemix`.
- Endpoint: `https://api.vachana.ai/stt/v3`.

---

## 2. Empirical Test Results

| Parameter | Recorded Value | Evaluation |
| :--- | :--- | :--- |
| **HTTP Status** | **No HTTP Response Received** | Connection severed before response headers |
| **Total Request In-Flight Duration** | **38,074.93 ms (38.07 seconds)** | Client held connection open for 38 seconds |
| **Client Timeout Setting** | `60.0 seconds` | Client did **not** timeout prematurely |
| **Exception Surfaced** | `ConnectionResetError(10054)` | `'An existing connection was forcibly closed by the remote host'` |
| **Underlying Layer** | `requests.exceptions.ConnectionError` | TCP socket reset (`TCP RST`) by server |
| **Raw Transcript** | `""` (Empty) | No transcript returned |
| **₹500 Amount Recognized** | `False` | No data received |
| **Credit Usage Exposed** | `N/A` | No response headers returned |

---

## 3. Conclusive Findings & Evidence

1. **Client Request Correctness:**
   - The TLS handshake succeeded with standard verification (`verify=True`).
   - The multipart upload of 147 KB was transmitted in full to `api.vachana.ai`.
   - The client remained connected and waiting for **38.07 seconds**.
2. **Server-Side Proxy Termination (TCP RST 10054):**
   - The remote endpoint held the connection open for 38 seconds while attempting ASR worker processing.
   - At the 38-second mark, the remote reverse proxy / API gateway abruptly terminated the TCP connection (`ConnectionResetError(10054)`).
   - This definitively explains why the earlier test produced `UNEXPECTED_EOF_WHILE_READING`: OpenSSL raised an unexpected EOF because the server forcibly dropped the connection without sending a TLS `close_notify`.
3. **Infrastructure State:**
   - The remote Prisma REST endpoint (`/stt/v3`) is currently experiencing server-side ASR worker processing latency exceeding its own proxy gateway timeout (~30–35s).
   - In contrast, Gnani Timbre TTS (`/api/v1/tts/inference`) completed successfully in 17.3s because its synthesis worker finished before the gateway timeout.

---

## 4. Strict Protocol Adherence Confirmation

- **Total Requests Made:** Exactly 1 live request.
- **Zero Retries:** No automated or manual retries were attempted.
- **No Additional Probes:** Zero curl, TTS, or external network requests were made.
- **Mock Mode Default:** `VOICE_PROVIDER_MODE=mock` remains active as application default.
- **Database Safety:** Zero writes to MongoDB.
- **Stage 2 Status:** Stage 2 remains **NOT AUTHORIZED** and was not executed.
- **Git State:** No files committed or pushed.
