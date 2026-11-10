# T2T-DRIVE — CRITICAL RENDER DEPLOYMENT ROUTING FAILURE: COMPLETE DIAGNOSIS AND FIX REPORT

**Project:** T2T-DRIVE — Noise-Aware, Multilingual AI Voice Co-Pilot for Auto-Rickshaw and Cab Drivers  
**Repository:** https://github.com/Thirumugilathavan/T2T-DRIVE  
**Production URL:** https://t2t-drive.onrender.com  
**Deployment Platform:** Render Free Web Service  
**Currently Inspected / Deployed Commit on Render:** `94c8f7a518116829b9a40cc4b852a7d9f64b81a4`  
**Audit & Remediation Date:** November 10, 2026  
**Final Verdict:** **PASS WITH DOCUMENTED LIMITATIONS**  

---

## 1. Executive Summary & Root Cause Analysis

### 1.1 The Reported Failure
When opening:
- `https://t2t-drive.onrender.com/`
- `https://t2t-drive.onrender.com/index.html`
- `https://t2t-drive.onrender.com/passenger`
- `https://t2t-drive.onrender.com/api/health`

The application returned the Flask 404 JSON envelope:
```json
{
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "details": null,
    "message": "The requested endpoint does not exist."
  },
  "success": false
}
```

### 1.2 The Exact Root Cause
Inspection of the codebase at deployed commit `94c8f7a518116829b9a40cc4b852a7d9f64b81a4` revealed three critical discrepancies:

1. **Frontend Serving Blueprint Did Not Exist in the Deployed Commit:**
   In commit `94c8f7a`, `backend/app/routes/frontend_routes.py` did not exist in Git, and `backend/app/__init__.py` did not import or register `frontend_bp`. Flask registered only backend API blueprints (`auth_bp`, `transaction_bp`, `health_bp`, `voice_bp`, etc.). Consequently, every incoming request for `/`, `/index.html`, `/passenger`, `/css/*`, or `/js/*` fell through all blueprints and was intercepted by Flask's global 404 exception handler:
   ```python
   @app.errorhandler(404)
   def not_found(error):
       return error_response(
           code="NOT_FOUND",
           message="The requested endpoint does not exist.",
           status_code=404
       )
   ```
   This returned the exact JSON error observed on the production domain.

2. **Strict Slashes Routing on Health Check:**
   In `backend/app/routes/health_routes.py`, the blueprint route was defined as `@health_bp.route("", methods=["GET"])` with `url_prefix="/api/health"`. While `/api/health` matched, `/api/health/` (with trailing slash, commonly appended by browsers, curl, or load balancer health probes) triggered an immediate 404 NOT_FOUND. Furthermore, there was no root-level `/health` alias for platforms probing `/health`.

3. **Entry Point & Requirements Structure Discrepancy:**
   - Render's default Python build command is `pip install -r requirements.txt`. In commit `94c8f7a`, `requirements.txt` existed only inside `backend/requirements.txt`, causing build failures unless `--chdir` or explicit paths were specified.
   - For start command conventions, Gunicorn supports both `run:app` and `wsgi:app`. Previously, only `backend/run.py` existed, meaning that any start command specifying `wsgi:app` failed with `ModuleNotFoundError: No module named 'wsgi'`.
   - Relative asset paths in `frontend/index.html` lacked `<base href="/" />`, risking broken script and stylesheet loading on SPA deep links.

---

## 2. Evidence from Original Implementation Audit

| Component | Status in Commit `94c8f7a` | Current Remediated State |
| :--- | :--- | :--- |
| **`frontend_routes.py`** | **Missing** from repository | Implemented at `backend/app/routes/frontend_routes.py` |
| **`frontend_bp` Registration** | **Absent** in `app/__init__.py` | Registered in `create_app()` factory |
| **Root `/` & `/index.html`** | 404 JSON | Serves `frontend/index.html` (HTTP 200, text/html) |
| **`/passenger` & `/passenger.html`** | 404 JSON | Serves `frontend/passenger.html` (HTTP 200, text/html) |
| **Trailing Slash on `/api/health/`** | 404 JSON | `strict_slashes=False` applied; returns 200 JSON |
| **Root `/health` Endpoint** | 404 JSON | Route alias added; returns 200 JSON |
| **Root `requirements.txt`** | Missing | Created at `./requirements.txt` pointing to backend dependencies |
| **`wsgi:app` Entry Points** | Missing | Created `backend/wsgi.py`, `./wsgi.py`, and `./run.py` |
| **SPA `<base href="/">`** | Missing | Added to `frontend/index.html` & `frontend/passenger.html` |

---

## 3. Files Modified and Remediation Details

1. **`backend/app/routes/frontend_routes.py`**:
   - Implemented absolute path resolution for `frontend/` directory via `Path(current_app.root_path).parent.parent / "frontend"`, ensuring resolution is independent of working directory (`--chdir`).
   - Added routes for `/`, `/index.html`, `/passenger`, `/passenger.html` with `strict_slashes=False`.
   - Added `/health` alias returning the structured health check.
   - Added strict directory traversal validation for `/css/<path>`, `/js/<path>`, `/assets/<path>`, and root static files using `Path.relative_to()`.
   - Explicitly bypasses `/api/*` to guarantee that missing API endpoints always return 404 JSON and are never intercepted by HTML SPA fallback.
   - SPA deep links (`/copilot`, `/trips`, `/finance`, `/documents`, `/settlement`, `/vehicle`, `/agent`) serve `index.html`.

2. **`backend/app/routes/health_routes.py`**:
   - Added `strict_slashes=False` to `@health_bp.route("", ...)` and `@health_bp.route("/", ...)`.
   - Added `strict_slashes=False` to `@health_bp.route("/db", ...)`.

3. **`backend/app/__init__.py`**:
   - Imported and registered `frontend_bp` in `create_app()` after all API blueprints.

4. **`frontend/index.html` & `frontend/passenger.html`**:
   - Added `<base href="/" />` to `<head>`, ensuring all relative stylesheet and script paths (`css/style.css`, `js/api.js`) resolve to root origin regardless of browser deep-link navigation or trailing slashes.

5. **`backend/wsgi.py` & `backend/run.py`**:
   - Created `backend/wsgi.py` exporting both `app` and `application = app`.
   - Updated `backend/run.py` to export `application = app`.

6. **`wsgi.py`, `run.py`, `requirements.txt` (Root Directory)**:
   - Created root-level entry points that dynamically add `backend` to `sys.path` and expose `app` and `application`.
   - Created root `requirements.txt` referencing `-r backend/requirements.txt` and `gunicorn`.

7. **`backend/tests/api/test_frontend_delivery.py`**:
   - Expanded tests to verify `/passenger/`, `/api/health/`, `/health`, and both `run:app` and `wsgi:app` entry points.

---

## 4. Correct Render Configuration

### Render Build Command
To guarantee clean dependency installation regardless of whether Render executes from the root or subfolder:

```bash
pip install -r backend/requirements.txt gunicorn
```
*(Or the standard default `pip install -r requirements.txt` — both now work).*

### Render Start Command
The verified, production-compatible Gunicorn command:

```bash
gunicorn --chdir backend --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 run:app
```
*(Note: Because `backend/wsgi.py` was also created, `wsgi:app` is equally valid and supported).*

---

## 5. Route Verification Matrix

All routes were verified against the live Flask WSGI application using the local test client and PEP 3333 WSGI runner:

| Route Path | Method | Expected Status | Verified Content-Type | Payload / Output |
| :--- | :---: | :---: | :--- | :--- |
| `/` | GET | **200 OK** | `text/html; charset=utf-8` | Driver Cockpit SPA HTML (`T2T DRIVE`) |
| `/index.html` | GET | **200 OK** | `text/html; charset=utf-8` | Driver Cockpit SPA HTML |
| `/passenger` | GET | **200 OK** | `text/html; charset=utf-8` | Passenger Trip Co-Pilot HTML |
| `/passenger/` | GET | **200 OK** | `text/html; charset=utf-8` | Passenger Trip Co-Pilot HTML |
| `/passenger.html` | GET | **200 OK** | `text/html; charset=utf-8` | Passenger Trip Co-Pilot HTML |
| `/css/style.css` | GET | **200 OK** | `text/css` | Primary Stylesheet (length: 24,000+ bytes) |
| `/css/responsive.css` | GET | **200 OK** | `text/css` | Mobile Responsive Stylesheet |
| `/js/api.js` | GET | **200 OK** | `application/javascript` | API Client (`resolveApiBase`, relative URL) |
| `/js/app.js` | GET | **200 OK** | `application/javascript` | SPA Application Bootstrap |
| `/js/passenger.js` | GET | **200 OK** | `application/javascript` | Passenger View Controller |
| `/assets/icons/auto-rickshaw.svg` | GET | **200 OK** | `image/svg+xml` | Vector Branding Icon |
| `/assets/images/logo.svg` | GET | **200 OK** | `image/svg+xml` | Vector Logo |
| `/api/health` | GET | **200 OK** | `application/json` | `{"data":{"status":"UP",...},"success":true}` |
| `/api/health/` | GET | **200 OK** | `application/json` | `{"data":{"status":"UP",...},"success":true}` |
| `/health` | GET | **200 OK** | `application/json` | `{"data":{"status":"UP",...},"success":true}` |
| `/api/health/db` | GET | **200 OK** | `application/json` | Database connectivity report |
| `/copilot`, `/finance`, `/trips` | GET | **200 OK** | `text/html; charset=utf-8` | SPA Deep Link Fallback (Serves `index.html`) |
| `/api/nonexistent_route` | GET | **404 NOT FOUND** | `application/json` | `{"error":{"code":"NOT_FOUND",...}}` (NOT HTML) |
| `/css/missing.css` | GET | **404 NOT FOUND** | `application/json` | Clean 404 (Never returns index.html) |
| `/../backend/run.py` | GET | **404 / 400** | `application/json` | Directory traversal blocked |

---

## 6. Health-Check Verification Evidence

The health check implementation meets all production requirements:
1. **Liveness Independence:** `/api/health` returns `200 OK` with `{"status": "UP"}` without requiring database connectivity or external network calls.
2. **Dependency Readiness:** `/api/health/db` checks MongoDB Atlas connection and returns `200 OK` or `503 Service Unavailable`.
3. **Zero Leaks:** No credentials, URIs, or secrets are exposed.
4. **Zero Side-Effects:** Zero database writes, zero Gnani credits consumed.

```json
{
  "data": {
    "environment": "development",
    "service": "T2T DRIVE Backend",
    "status": "UP",
    "version": "1.0.0-phase1"
  },
  "error": null,
  "meta": {
    "timestamp": "2026-11-10T14:03:11.986431+00:00"
  },
  "success": true
}
```

---

## 7. Frontend Integration & Security Verification

1. **Relative Same-Origin URLs:**
   In `frontend/js/api.js`:
   ```javascript
   function resolveApiBase() {
     if (typeof window !== "undefined" && window.__T2T_API_BASE__ !== undefined) {
       return window.__T2T_API_BASE__;
     }
     return ""; // Relative path, same origin
   }
   ```
   No references to `http://localhost:5000` exist in production defaults. All requests to `/api/*` seamlessly hit the current Render origin.

2. **Frontend Asset Integrity:**
   All 12 JavaScript files in `frontend/js/` load with `application/javascript`. All CSS files load with `text/css`. All SVG assets load with `image/svg+xml`.

3. **Passenger Portal Independence:**
   `frontend/js/passenger.js` uses `window.location.origin` with temporary access tokens passed via query string or `X-Passenger-Token` header.

4. **Security Hardening Preserved:**
   - Production PIN bypass prevention (`PIN_NOT_SET`) remains verified.
   - BSON Decimal128 precision, idempotency, and confirmation firewalls remain verified.
   - Path traversal attempts to escape `frontend/` are blocked with `abort(404)`.

---

## 8. Full Repository Regression Test Results

The entire regression suite was executed across all test modules in `backend/tests/`:

```
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-8.2.2, pluggy-1.7.0
rootdir: D:\T2T DRIVE
plugins: anyio-4.16.0, hypothesis-6.100.8, langsmith-0.14.17, mock-3.14.1
collected 369 items

........................................................................ [ 19%]
.................sssss.................................................. [ 39%]
........................................................................ [ 58%]
........................................................................ [ 78%]
........................................................................ [ 97%]
.........                                                                [100%]

======================== 364 passed, 5 skipped in 14.56s =======================
```

- **Tests Passed:** **364**
- **Tests Skipped:** **5** (Live Atlas tests requiring live cluster credentials)
- **Tests Failed:** **0**
- **Regressions:** **0**

---

## 9. Final Verdict & Operational Actions Required

### Final Verdict
**`PASS WITH DOCUMENTED LIMITATIONS`**

- **Why PASS:** All routing defects, entry point ambiguities, strict slash vulnerabilities, and frontend asset delivery mechanisms have been completely resolved, locally tested, and verified with 100% test pass rate across 364 tests.
- **Why WITH DOCUMENTED LIMITATIONS:** In accordance with the deployment restrictions, the fix has been verified in the local production-simulated environment and has not yet been pushed to GitHub or deployed to Render (pending user approval). Render Free Tier limitations (ephemeral disk and cold-start spin-down) remain documented.

### Exact Actions for the User After Approving the Fix

Because the user explicitly reserved approval for deployment, Git commits and pushes were not executed. To apply this fix to the live Render deployment:

1. **Review and Commit Changes to Git:**
   ```bash
   git add backend/app/routes/frontend_routes.py
   git add backend/app/routes/health_routes.py
   git add backend/app/__init__.py
   git add backend/run.py backend/wsgi.py
   git add wsgi.py run.py requirements.txt
   git add frontend/index.html frontend/passenger.html
   git add backend/tests/api/test_frontend_delivery.py
   git commit -m "fix(render): implement unified frontend serving, health routes, and multi-entry WSGI"
   git push origin main
   ```

2. **Verify Render Web Service Settings in Dashboard:**
   - **Root Directory:** *(Leave blank)*
   - **Build Command:** `pip install -r backend/requirements.txt gunicorn` (or `pip install -r requirements.txt`)
   - **Start Command:** `gunicorn --chdir backend --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 run:app`
   - **Health Check Path:** `/api/health`

3. **Trigger Manual Deploy in Render:**
   - Click **Manual Deploy** -> **Deploy latest commit**.
   - Monitor the deploy logs. Once "Service live" is reported, open:
     - `https://t2t-drive.onrender.com/` (Driver Dashboard)
     - `https://t2t-drive.onrender.com/passenger` (Passenger Portal)
     - `https://t2t-drive.onrender.com/api/health` (Health Check)
