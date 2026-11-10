# T2T-DRIVE — PRODUCTION SECURITY AUDIT REPORT

**System:** T2T-DRIVE (Noise-Aware Multilingual Voice Co-Pilot for Auto-Rickshaw and Cab Drivers)  
**Target:** Batch 3 Production Hardening and Security Baseline  
**Audit Date:** November 10, 2026  
**Auditor Status:** Automated Verification & Architecture Audit Suite  
**Overall Security Status:** **PASSED — HARDENED FOR PRODUCTION**  

---

## 1. Authentication & Session Security

### 1.1 OTP Generation & Verification
- **Cryptographic Randomness:** OTPs are generated using Python's `secrets.randbelow(900000) + 100000`, guaranteeing cryptographically secure 6-digit pseudorandom values.
- **Hashed Storage in MongoDB:** Plaintext OTPs are **never stored** in the database. OTPs are hashed using keyed HMAC-SHA-256 with a dedicated `OTP_HASH_SECRET`.
- **Constant-Time Verification:** Verification is performed exclusively in Python using `hmac.compare_digest`, effectively neutralizing timing side-channel attacks.
- **Anti-Replay & Atomic Single-Use:** Verified using MongoDB's atomic `find_one_and_update({"_id": id, "is_used": False}, {"$set": {"is_used": True}})`. Replay submissions receive `INVALID_OTP`.
- **Brute-Force Protection:** Counter increments atomically on each failed attempt. Reaching 3 failed attempts permanently invalidates the OTP (`MAX_ATTEMPTS_EXCEEDED`).
- **Rate Limiting:** Drivers cannot request more than 3 OTPs per 10-minute sliding window (`RATE_LIMIT_EXCEEDED`).

### 1.2 PIN Authentication Hardening
- **Production Bypass Prevention:** In development mode, accounts without a stored PIN hash could use `'1234'`. In production mode (`FLASK_ENV="production"`), `AuthService.verify_pin` strictly rejects any driver account without an explicit `pin_hash`, returning `PIN_NOT_SET`.
- **Constant-Time Hash Comparison:** When configured, PINs are salted with `SECRET_KEY` and compared with constant-time cryptographic equality.

### 1.3 JWT Integrity & Server-Side Revocation
- **Signing Algorithm:** HS256 with strong >= 32-character keys enforced at startup by `ProductionConfig.validate()`.
- **Tampering Detection:** Tampered token signatures trigger `jwt.InvalidSignatureError` and are rejected with HTTP 401.
- **Unique JTI Tokens:** Every issued JWT embeds a unique `jti` identifier and expiration claim (`exp`).
- **Stateful Revocation:** Driver logout invokes `auth_svc.revoke_token(jti, ...)`. Revocations are persisted in the `revoked_tokens` MongoDB collection with automated TTL index expiration matching token lifespan.

---

## 2. Multi-Tenant Data Isolation

### 2.1 Driver Tenant Boundary
- Every authenticated request extracts `g.driver_id` from the verified JWT payload.
- Repository queries on transactions, vehicle documents, sessions, and maintenance records explicitly scope queries by `driver_id`:
  - `ledger_service.get_transaction(txn_id, driver_id=g.driver_id)` returns `None` if the transaction belongs to another driver.
  - API endpoints return HTTP 404 `TRANSACTION_NOT_FOUND` on cross-tenant access attempts.
  - Driver A cannot list or view Driver B's ledger entries.

### 2.2 Passenger Token Trip Isolation
- Passenger access tokens use cryptographically random 32-byte URL-safe tokens (`secrets.token_urlsafe(32)`).
- Tokens are stored in MongoDB only as keyed HMAC-SHA-256 hashes (`token_hash`).
- Each token is strictly bound to a single `trip_id`.
- Attempting to access Trip B with a token generated for Trip A raises `PassengerAccessUnauthorizedError` ("Token is not authorized for this trip.").
- Driver ending or cancelling a trip triggers `revoke_access(trip_id)`, immediately invalidating the passenger link with `PassengerAccessExpiredError`.

---

## 3. Storage & File Upload Hardening

### 3.1 Format & Magic-Byte Validation
- Extension filtering alone is recognized as vulnerable to file-renaming attacks.
- `LocalStorageAdapter.validate_file()` enforces strict binary magic-byte inspection:
  - `.pdf`: Must begin with `b"%PDF"`
  - `.png`: Must begin with `b"\x89PNG\r\n\x1a\n"`
  - `.jpg` / `.jpeg`: Must begin with `b"\xff\xd8\xff"`
- Renamed malicious executables or text scripts are immediately rejected with `ValueError: File content does not match expected format`.

### 3.2 Directory Traversal Defenses
- File references are normalized via `os.path.normpath` with stripped leading path separators.
- Resolved file paths are verified against `self.base_dir` using `os.path.abspath(path).startswith(self.base_dir)`.
- Traversal attempts (e.g. `../../../etc/passwd` or `..\..\Windows`) immediately raise `PermissionError` ("Access denied: Invalid file path traversal detected.").

### 3.3 Upload Limits
- Upload payload size is enforced before reading into memory, capped at `DOCUMENT_MAX_UPLOAD_MB` (default 10 MB).

---

## 4. API Error Sanitization

- All unhandled exceptions are caught by unified application error handlers.
- Errors are returned in a standard envelope:
  ```json
  {
    "success": false,
    "error": {
      "code": "ERROR_CODE",
      "message": "Sanitized user-facing message.",
      "details": null
    }
  }
  ```
- No Python tracebacks, database connection strings, or system paths are exposed to the client.

---

## 5. Security Test Suite Evidence

A dedicated security hardening regression suite was executed via `pytest backend/tests/security/test_security_hardening.py`:

```
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_production_pin_bypass_rejection PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_production_secret_strength_validation PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_jwt_tampering_and_revocation PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_cross_tenant_driver_isolation PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_passenger_token_trip_binding PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_document_storage_magic_bytes_and_traversal PASSED
backend/tests/security/test_security_hardening.py::TestSecurityHardening::test_otp_rate_limiting_and_anti_replay PASSED

======================== 7 passed in 3.50s ========================
```
