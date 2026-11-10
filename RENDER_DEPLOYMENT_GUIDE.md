# T2T-DRIVE — RENDER DEPLOYMENT GUIDE

This guide provides step-by-step instructions for deploying T2T-DRIVE as a unified Web Service on the Render Free Tier platform.

---

## 1. Architecture Overview on Render

T2T-DRIVE runs as a single, unified web service:
- **Backend Entry Point:** Python / Flask WSGI application managed by Gunicorn.
- **Frontend Hosting:** Static assets (`frontend/index.html`, `frontend/passenger.html`, `frontend/css/`, `frontend/js/`) are served directly by the Flask application at `/` and `/passenger`.
- **API Routing:** Dynamic REST and Voice APIs are served under the same origin at `/api/*`.
- **Database:** Remote MongoDB Atlas cluster (M0 Free Tier or dedicated replica set).
- **Voice Intelligence:** External calls from the backend to Gnani AI Prisma STT and Timbre TTS.

---

## 2. Prerequisites
1. A GitHub repository containing the complete T2T-DRIVE codebase (`https://github.com/Thirumugilathavan/T2T-DRIVE`).
2. A free Render account at [render.com](https://render.com).
3. A MongoDB Atlas cluster with network access allowed from all IPs (`0.0.0.0/0`) since Render Free instances use dynamic outbound IPs.
4. A Gnani AI API Key for real voice processing.

---

## 3. Step-by-Step Render Setup

### Step 1: Create a New Web Service
1. Log into your Render Dashboard.
2. Click **New +** -> **Web Service**.
3. Connect your GitHub account and select the **T2T-DRIVE** repository.

### Step 2: Configure Service Details
- **Name:** `t2t-drive` (or your preferred unique service name)
- **Region:** `Singapore (Southeast Asia)` or `Frankfurt (EU Central)` (closest to India for minimal latency)
- **Branch:** `main`
- **Root Directory:** *(Leave completely empty — root of repository)*
- **Runtime:** `Python 3`

### Step 3: Specify Build & Start Commands
- **Build Command:**
  ```bash
  pip install --upgrade pip && pip install -r requirements.txt
  ```
  *(Note: `requirements.txt` exists at repository root and points to the production dependencies)*

- **Start Command:**
  ```bash
  gunicorn --chdir backend --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT wsgi:app
  ```

> [!IMPORTANT]
> - Render Free instances have 512 MB of RAM. Using `--workers 1 --threads 4` ensures high concurrency without triggering Linux OOM (Out Of Memory) kills.
> - The `--timeout 120` prevents Gunicorn from killing worker processes during longer voice transcription turns or cold-start database handshakes.

### Step 4: Configure Environment Variables
Under the **Environment** tab, add the environment variables defined in `PRODUCTION_ENVIRONMENT_VARIABLES.md`:
1. `FLASK_ENV`: `production`
2. `SECRET_KEY`: *(Generate a secure 64-character random string)*
3. `JWT_SECRET`: *(Generate a second secure 64-character random string)*
4. `OTP_HASH_SECRET`: *(Generate a third secure 64-character random string)*
5. `MONGODB_URI`: `mongodb+srv://<user>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority`
6. `DB_NAME`: `t2t_drive_prod`
7. `VOICE_PROVIDER_MODE`: `live`
8. `GNANI_API_KEY`: `your_live_gnani_key`
9. `GNANI_PRISMA_ENABLED`: `1`
10. `GNANI_TIMBRE_ENABLED`: `1`
11. `DOCUMENT_STORAGE_MODE`: `local`
12. `DOCUMENT_STORAGE_PATH`: `uploads/documents`

### Step 5: Configure Health Check
Under **Advanced**:
- **Health Check Path:** `/api/health`

Render will periodically poll `/api/health` to confirm that the Flask application and MongoDB connection are healthy before directing incoming traffic.

---

## 4. Verification Post-Deployment

Once Render reports **Service Live**:

1. **Verify Health Endpoint:**
   ```bash
   curl -i https://<your-service>.onrender.com/api/health
   ```
   *Expected response: HTTP 200 with `{"data":{"status":"HEALTHY","db_status":"CONNECTED"}}`*

2. **Verify Frontend UI Delivery:**
   - Open `https://<your-service>.onrender.com/` in your mobile or desktop browser. The Driver Voice Dashboard should load immediately.
   - Open `https://<your-service>.onrender.com/passenger` in a browser. The Passenger Trip Tracking interface should load cleanly.

3. **Verify Voice Capabilities:**
   ```bash
   curl -s https://<your-service>.onrender.com/api/voice/capabilities
   ```
   *Expected response: `{"data":{"mode":"live","prisma_enabled":true,"timbre_enabled":true}}`*

---

## 5. Render Free Tier Operational Considerations

- **Cold Starts:** After 15 minutes of inactivity, Render Free web services spin down to conserve compute resources. The first request after spin-down may take ~45–60 seconds to respond. Subsequent requests will respond in milliseconds.
- **Ephemeral Filesystem:** Any files uploaded to `uploads/documents/` will be deleted when the container restarts. For long-term production storage, see `KNOWN_LIMITATIONS.md` for the recommended AWS S3 / Cloudinary adapter integration.
