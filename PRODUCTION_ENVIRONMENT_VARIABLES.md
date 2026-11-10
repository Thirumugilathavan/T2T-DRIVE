# T2T-DRIVE — PRODUCTION ENVIRONMENT VARIABLES REFERENCE

This document provides the complete, authoritative reference of all environment variables required for deploying T2T-DRIVE in production on Render or any cloud container environment.

---

## 1. Environment Variables Reference Table

| Variable Name | Required | Sensitivity | Default / Example Value | Description |
| :--- | :---: | :---: | :--- | :--- |
| `FLASK_ENV` | **Yes** | CONFIG | `production` | Sets the application runtime environment. Disables debug mode and activates `ProductionConfig` validation. |
| `PORT` | **Yes** (Automated) | CONFIG | `10000` (Injected by Render) | Port on which the Gunicorn WSGI server listens. Render sets this automatically. |
| `SECRET_KEY` | **Yes** | **CRITICAL** | `min-32-char-cryptographic-random-secret` | Flask session cookie signing and cryptographic CSRF salt. Must be >= 32 characters. |
| `JWT_SECRET` | **Yes** | **CRITICAL** | `min-32-char-cryptographic-jwt-secret-key` | Secret used to sign and verify HS256 driver JWT tokens. Must be >= 32 characters and distinct from `SECRET_KEY`. |
| `OTP_HASH_SECRET` | **Yes** | **CRITICAL** | `min-32-char-cryptographic-otp-hash-key` | Dedicated HMAC-SHA-256 secret for hashing OTP tokens stored in MongoDB. Never store plaintext OTPs. |
| `MONGODB_URI` | **Yes** | **SECRET** | `mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority` | Full MongoDB Atlas connection string with replica set and TLS verification enabled. |
| `DB_NAME` | **Yes** | CONFIG | `t2t_drive_prod` | Name of the primary production MongoDB database. |
| `VOICE_PROVIDER_MODE` | **Yes** | CONFIG | `live` | Voice integration engine mode: `live` for real Gnani AI, `mock` for automated testing. |
| `GNANI_API_KEY` | **Yes** (in live mode) | **SECRET** | `your_gnani_vachana_api_key_here` | API authorization key for Gnani AI Prisma STT and Timbre TTS services. Kept exclusively on backend. |
| `GNANI_PRISMA_ENABLED` | Optional | CONFIG | `1` | `1` to enable live Prisma STT transcription; `0` to disable STT with graceful user prompt. |
| `GNANI_TIMBRE_ENABLED` | Optional | CONFIG | `1` | `1` to enable live Timbre TTS speech synthesis; `0` to disable TTS. |
| `GNANI_BASE_URL` | Optional | CONFIG | `https://api.vachana.ai` | Base URL for Gnani AI REST gateway services. |
| `GNANI_PRISMA_ENDPOINT` | Optional | CONFIG | `https://api.vachana.ai/stt/v3` | REST endpoint for Gnani Prisma STT v3.0 transcription. |
| `GNANI_TIMBRE_ENDPOINT` | Optional | CONFIG | `https://api.vachana.ai/api/v1/tts/inference` | REST endpoint for Gnani Timbre TTS speech synthesis. |
| `SMS_PROVIDER_MODE` | Optional | CONFIG | `mock` (or `live`) | Mode for SMS OTP dispatch. In `mock`, OTP is generated and logged safely without SMS charges. |
| `SMS_API_KEY` | Optional | SECRET | `your_sms_gateway_api_key` | API key for third-party SMS provider (e.g. Fast2SMS / Twilio). |
| `SMS_SENDER_ID` | Optional | CONFIG | `T2TDRV` | Registered 6-character DLT sender header for SMS dispatch in India. |
| `DOCUMENT_STORAGE_MODE` | Optional | CONFIG | `local` | Document storage adapter mode: `local` filesystem storage. |
| `DOCUMENT_STORAGE_PATH` | Optional | CONFIG | `uploads/documents` | Filesystem path for private document uploads. |
| `DOCUMENT_MAX_UPLOAD_MB` | Optional | CONFIG | `10` | Maximum upload size for driver documents and vehicle challans (in megabytes). |
| `RENDER_EXTERNAL_URL` | Optional | CONFIG | `https://t2t-drive.onrender.com` | Public HTTPS URL assigned by Render; automatically added to CORS allowed origins. |
| `ALLOWED_ORIGINS` | Optional | CONFIG | `https://t2t-drive.onrender.com` | Comma-delimited list of permitted CORS origins. |

---

## 2. Safe Template for Render Environment Variables

To configure these in the **Render Dashboard -> Environment -> Environment Variables**, copy and fill in the values below:

```env
# Core Runtime
FLASK_ENV=production
SECRET_KEY=replace_with_64_character_hex_random_string_generator
JWT_SECRET=replace_with_different_64_character_hex_random_string
OTP_HASH_SECRET=replace_with_third_distinct_64_character_hex_string

# Database
MONGODB_URI=mongodb+srv://<db_user>:<db_password>@t2t-cluster.mongodb.net/?retryWrites=true&w=majority
DB_NAME=t2t_drive_prod

# Gnani Voice AI (Live Mode)
VOICE_PROVIDER_MODE=live
GNANI_API_KEY=your_actual_gnani_api_key
GNANI_PRISMA_ENABLED=1
GNANI_TIMBRE_ENABLED=1
GNANI_BASE_URL=https://api.vachana.ai
GNANI_PRISMA_ENDPOINT=https://api.vachana.ai/stt/v3
GNANI_TIMBRE_ENDPOINT=https://api.vachana.ai/api/v1/tts/inference

# SMS & Storage
SMS_PROVIDER_MODE=mock
DOCUMENT_STORAGE_MODE=local
DOCUMENT_STORAGE_PATH=uploads/documents
DOCUMENT_MAX_UPLOAD_MB=10

# Security & CORS
RENDER_EXTERNAL_URL=https://<your-service-name>.onrender.com
ALLOWED_ORIGINS=https://<your-service-name>.onrender.com
```

> [!CAUTION]
> **Never commit `.env` or paste real API keys into git repositories.** Keep all secrets strictly inside Render's encrypted environment variables manager.
