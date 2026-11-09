# T2T DRIVE — Audio Data Privacy & Ephemeral Processing Architecture

## 1. Principles & Purpose

T2T DRIVE is deployed on mobile smartphones mounted on vehicle dashboards. Drivers engage with the application in private or commercial vehicle cabins.
Under the **Digital Personal Data Protection Act, 2023 (DPDP)** and industry data security standards, voice recordings are sensitive personal information.

The audio architecture adheres to four core privacy principles:
1. **Purpose Limitation:** Voice audio is processed solely to recognize financial/vehicle commands.
2. **Storage Limitation (Ephemeral In-Memory Only):** Raw voice audio is never stored permanently on disk or stored in MongoDB.
3. **Data Minimization:** Only non-identifiable acoustic telemetry (dBFS, SNR, duration, noise classification) is retained for service observability.
4. **Driver Consent & Control:** Microphone access is strictly driver-initiated (Push-to-Talk) with zero continuous ambient eavesdropping.

---

## 2. In-Memory Ephemeral Pipeline

```
[Driver Device] ──(HTTPS/TLS 1.3)──► [Flask Memory: BytesIO]
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
          [Pre-Flight Noise Engine]                       [Gnani Prisma STT]
          - In-memory PCM unpack                          - In-memory streaming
          - In-memory 120Hz filter                        - Returns text transcript
          - In-memory normalization                                │
                       │                                           ▼
                       ▼                                  [LangGraph Agent]
          [Acoustic Telemetry Record]                              │
          (RMS dBFS, SNR, Noise Category)                          ▼
                       │                                  [Confirmation Card]
                       ▼                                           │
          [Saved to Audit Log]                                     ▼
                                                          [Request Terminates]
                                                          - BytesIO garbage collected
                                                          - Zero disk traces retained
```

### 2.1 Complete Destruction of Audio Payloads
- Incoming audio bytes are received via Flask's `request.files` as an in-memory stream.
- Audio metrics and preprocessing transformations operate strictly in memory using Python standard library `struct` and `io.BytesIO`.
- When the HTTP response terminates, Python's automatic garbage collection reclaims the byte arrays.
- No audio files are written to the server's local filesystem or persisted in MongoDB Atlas.

### 2.2 Secure Temporary File Hygiene
If third-party SDKs or legacy adapters require a physical filesystem path:
1. Files are created in the OS temporary directory (`tempfile.NamedTemporaryFile`).
2. Immediate cleanup is guaranteed using standard Python `try ... finally` blocks:
   ```python
   temp_path = None
   try:
       temp_path = create_secure_temp_wav(audio_bytes)
       result = adapter.process(temp_path)
   finally:
       if temp_path and os.path.exists(temp_path):
           os.remove(temp_path)
   ```

---

## 3. Data Telemetry vs. Raw Audio

The application persists only acoustic telemetry metrics required to diagnose noisy environments and optimize recognition models:

| Metric Field | Stored in Database? | Identifiable Voice Data? | Purpose |
|:---|:---|:---|:---|
| **Raw Voice Audio** | **NO (Never)** | Yes | Destroyed immediately |
| **Acoustic Noise Floor** | Yes (e.g. `-38.2 dBFS`) | No | Telemetry & SNR calculation |
| **Estimated SNR** | Yes (e.g. `11.5 dB`) | No | Acoustic quality tracking |
| **Noise Classification** | Yes (e.g. `ENGINE_NOISE`) | No | Advisory display |
| **Voice Duration** | Yes (e.g. `1.85 s`) | No | Turn billing & bounds checking |
| **Recognized Transcript** | Yes (Text string) | Semi | Financial ledger record |

---

## 4. Multi-Tenant Driver Isolation

Every voice request requires a cryptographically validated JWT Bearer token:
- Requests without a valid JWT are rejected immediately with HTTP 401 Unauthorized before any audio parsing occurs.
- The `driver_id` extracted from the verified token scopes all database reads and writes.
- Drivers cannot access audio telemetry, transcripts, or financial records belonging to any other driver.

---

## 5. Zero Secret Exposure Guarantee

- API keys (`GNANI_API_KEY`, `GNANI_PRISMA_TOKEN`, `JWT_SECRET_KEY`) are read strictly from process environment variables.
- System capability discovery endpoints (`/api/voice/capabilities`) return boolean readiness flags (`LIVE` / `MOCK`) and model identifiers, explicitly suppressing all credential values.
- Automated API test `test_voice_capabilities` continuously asserts that secret keys never appear anywhere in API response envelopes.
