# T2T-DRIVE — KNOWN LIMITATIONS & PRODUCTION ADVISORIES

This document provides a transparent, rigorous audit of the known limitations, architectural trade-offs, and operational advisories for T2T-DRIVE.

---

## 1. Hosting & Infrastructure Limitations (Render Free Tier)

### 1.1 Ephemeral Container Filesystem
- **Current Behavior:** Uploaded driver documents (Insurance, PUC, RC, Driving Licence) and challan attachment receipts are stored on the local container disk at `uploads/documents/` via `LocalStorageAdapter`.
- **Limitation:** Render's Free Web Service runs inside an ephemeral Docker container. When the service spins down due to inactivity or restarts during redeployment, any files saved in `uploads/documents/` are deleted. Database metadata in MongoDB Atlas remains intact, but file retrieval requests will return 404.
- **Production Recommendation:** Replace `LocalStorageAdapter` with a cloud object storage adapter (AWS S3, Cloudinary, or Google Cloud Storage) using a signed-URL workflow. The `StorageAdapterBase` abstract class is already designed to support drop-in external adapters.

### 1.2 Inactivity Spin-Down & Cold-Start Latency
- **Current Behavior:** Render spins down free web services after 15 minutes of zero HTTP traffic.
- **Limitation:** The first request sent to a spun-down service experiences a cold-start delay of approximately 45–60 seconds while the Linux container boots, installs memory buffers, and connects to MongoDB.
- **Production Recommendation:** For production driver deployments, upgrade to a Render "Starter" or "Standard" persistent instance ($7/month) which eliminates spin-down, or implement a 10-minute HTTP ping schedule via a health check cron job.

### 1.3 Memory Constraints (512 MB RAM)
- **Current Behavior:** The Gunicorn start command is specifically tuned to `--workers 1 --threads 4` to prevent exceeding the 512 MB RAM ceiling.
- **Limitation:** Heavy concurrent audio uploads (multiple drivers sending 10 MB WAV files simultaneously) could strain memory if workers are increased beyond 1 on the free tier.
- **Production Recommendation:** Scale horizontally or increase container RAM to 1 GB+ if supporting fleets larger than 50 concurrent active drivers.

---

## 2. Voice AI & Third-Party Service Limitations

### 2.1 Live Gnani AI API Verification Status
- **Current Behavior:** During development and automated test runs, all STT and TTS verification was performed against high-fidelity mock adapters (`MockPrismaAdapter`, `MockTimbreAdapter`) and calibrated audio fixtures to adhere strictly to zero-credit consumption rules.
- **Limitation:** While the production runtime has been hardened with strict environment validation (`ProductionConfig.validate()` and live endpoints), end-to-end network transmission of real audio bytes to `api.vachana.ai` using live commercial credentials was not executed in this test environment.
- **Operational Advisory:** When first deploying with a live Gnani API key, perform a 1-turn manual smoke test using the driver voice UI to verify outbound HTTPS routing from your Render region to Gnani's gateway.

### 2.2 Compressed Web Audio Formats (WebM vs WAV)
- **Current Behavior:** Modern Chromium mobile browsers record microphone audio using MediaRecorder encoded as `audio/webm; codecs=opus`, while Safari on iOS records `audio/mp4`.
- **Limitation:** Python's built-in `wave` module cannot inspect raw WebM or MP4 headers.
- **Mitigation:** `AudioPreprocessor` includes fallback passthrough for compressed non-WAV streams, and Gnani Prisma v3.0 natively accepts WebM/MP4 container formats. However, client-side resampling to 16kHz Mono WAV remains the most optimal format for STT recognition accuracy.

---

## 3. Financial & Concurrency Considerations

### 3.1 MongoDB Atlas M0 Multi-Document Transaction Limits
- **Current Behavior:** Financial transactions utilize atomic single-document updates and two-phase pending action state transitions.
- **Limitation:** Shared M0 Free Tier clusters have strict 60-second transaction execution limits and do not support heavy multi-document cross-collection ACID transactions under high latency.
- **Mitigation:** The application implements idempotent single-winner state machines (`PENDING` -> `CONFIRMED` -> `CONSUMED`), guaranteeing financial consistency even without distributed multi-document transaction locks.

### 3.2 SMS Gateway in India (DLT Compliance)
- **Current Behavior:** The SMS service defaults to `SMS_PROVIDER_MODE="mock"`, logging OTPs safely without dispatching cellular SMS messages.
- **Operational Advisory:** To dispatch real SMS to Indian cellular numbers (+91), the operator must register a Principle Entity and SMS templates with an Indian Telecom DLT portal (e.g. Vilpower / Jio) and supply a valid DLT-approved Sender ID (`SMS_SENDER_ID`).
