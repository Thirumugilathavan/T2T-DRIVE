# T2T DRIVE — Phase 5 Completion Report
## Document Management, Expiry Tracking, Challan Assistance & Vehicle Maintenance

**Project:** T2T DRIVE (A Noise-Aware, Multilingual AI Voice Co-Pilot for Auto-Rickshaw and Cab Drivers)  
**Phase:** Phase 5 — Document Management, Expiry Tracking, Challan Assistance & Vehicle Maintenance  
**Date:** November 2026  
**Status:** COMPLETE & VERIFIED (183 Passing Automated Tests, 0 Regressions)

---

## 1. Executive Summary

Phase 5 extends T2T DRIVE beyond financial ledger transactions and conversational voice assistance to provide a comprehensive vehicle and compliance management suite. Auto-rickshaw and cab drivers face severe daily operational hazards including expired fitness certificates (FC), lapsed insurance, unmonitored pollution (PUC) expiries, traffic challan disputes, and unanticipated mechanical breakdowns.

Phase 5 addresses these problems natively within the T2T DRIVE core architecture:
1. **Document Vault:** Secure upload, storage, MIME/magic-byte validation, and masked retrieval of RC, Insurance, FC, PUC, Permits, and Driving Licences.
2. **Expiry Engine:** Timezone-aware (IST), milestone-based (30, 15, 7, 1, 0 days) proactive expiry detection with idempotent notification delivery.
3. **Challan Management:** Tracking of traffic violations, fine amounts (validated Decimals), payment settlements, and an untrusted OCR preview pipeline requiring mandatory driver confirmation.
4. **Maintenance Tracking:** Preventative service scheduling, odometer tracking, and seamless integration with Phase 2 Financial Ledger where maintenance expenses pass through explicit driver confirmation before committing to the ledger.
5. **Multilingual Agent Integration:** Natural conversational support in Tamil, Tanglish, and English for document checks, fine inquiries, upcoming service dates, and expense logging.

---

## 2. Architecture & Component Architecture

```
[ Driver Interaction ]
   │  Voice (Gnani Prisma STT / Timbre TTS) & Text Chat
   ▼
[ Multilingual NLU & LangGraph Orchestrator ]
   │
   ├── [ Document Service ] ───────► [ Local / Cloud Storage Adapter ]
   │        │                                (Magic Bytes, Traversal Defense)
   │        ▼
   ├── [ Reminder Service ] ───────► [ Notification Adapter ]
   │        │                                (Mock & Twilio/SMS Fallback)
   │        ▼
   ├── [ Challan Service ] ────────► [ Untrusted OCR Adapter ]
   │        │                                (Mandatory Driver Confirmation)
   │        ▼
   └── [ Maintenance Service ] ────► [ Pending Action Confirmation Firewall ]
            │                                │
            │  (Upon Driver Confirmation)    ▼
            └────────────────────────► [ Phase 2 Append-Only Financial Ledger ]
```

### Module 1: Vehicle & Driver Document Management
- **Domain Models (`app.models.vehicle_document`):** Strict enums for `DocumentType` (RC, INSURANCE, FITNESS, PUC, PERMIT, TAX_RECEIPT, DRIVING_LICENCE, BADGE, etc.), `ExpiryStatus` (ACTIVE, EXPIRING_SOON, EXPIRED, UNKNOWN), and `VerificationStatus`.
- **Storage Layer (`app.utils.storage`):** Pluggable `StorageAdapterBase` with `LocalStorageAdapter`. Validates magic bytes (`%PDF`, PNG signature `\x89PNG\r\n\x1a\n`, JPEG `\xFF\xD8\xFF`), enforces file size bounds (10 MB), sanitizes file names via secure hashing to defeat path traversal attacks, and stores files outside public web roots.
- **Superseding & Renewal:** Uploading a renewed document automatically marks previous active documents of the same category for that vehicle as `SUPERSEDED`, and dismisses pending reminders for the old document ID.
- **Privacy Masking:** Document numbers are masked in API responses (e.g., `TN-0****4821`).

### Module 2: Expiry Tracking & Threshold Reminders
- **Milestone Detection:** Evaluates expiration dates against exact threshold intervals:
  - 30 days remaining (Advance notice)
  - 15 days remaining (Action recommended)
  - 7 days remaining (Critical urgency)
  - 1 day remaining (Final warning)
  - 0 days remaining (Expired)
- **Timezone Accuracy:** All expiry boundary checks are computed in Indian Standard Time (`Asia/Kolkata`) using midnight-to-midnight horizons.
- **Idempotency Guarantee:** Reminder creation uses compound idempotency keys (`REM_{driver_id}_{document_id}_{threshold_days}_{expiry_date}`) indexed with MongoDB unique constraints. Scanning the expiry engine repeatedly on the same day generates 0 duplicate reminders and 0 duplicate SMS notifications.

### Module 3: Challan Management & Assistance
- **Lifecycle Transitions:** Strictly enforced state machine:
  - `UNPAID` ➔ `PAID`
  - `UNPAID` ➔ `DISPUTED`
  - `DISPUTED` ➔ `UNDER_REVIEW`
  - `UNDER_REVIEW` ➔ `CANCELLED` or `UNPAID`
- **OCR Assistance Abstraction:** Integrates `MockOCRAdapter` for simulated challan camera captures. Extracted fields (challan number, fine amount, violation notice) are explicitly tagged `is_verified: False` and `requires_confirmation: True`. Direct DB writes are prevented without explicit driver verification.
- **Money Handling:** Challan fines strictly use Python `Decimal` and MongoDB `Decimal128` to prevent IEEE 754 floating-point drift.

### Module 4: Vehicle Maintenance & Financial Ledger Integration
- **Category Normalization:** Categories (`ENGINE_OIL`, `BRAKE_SERVICING`, `TYRE_WORK`, `CLUTCH_OVERHAUL`, `ELECTRICAL`, `BATTERY`, `GENERAL_SERVICING`, etc.) support localized bilingual Tamil labels.
- **Confirmation Firewall:** Proposing a maintenance action with `record_financial_expense=True` creates an atomic `PENDING` action (`ADD_EXPENSE`). The financial ledger remains completely unchanged until the driver explicitly confirms.
- **Bi-directional Linkage:** Upon confirmation, the transaction is committed to the append-only transaction ledger (`TXN_...`), and the corresponding `MaintenanceRecord` is enriched with `financial_transaction_id`.
- **Idempotent Retry:** Client network timeouts during confirmation execute idempotently, generating exactly 1 transaction ledger entry and 1 maintenance log.

### Module 5: Multilingual Voice & Agent Integration
- **NLU Intent Extensions:**
  - `CHECK_DOCUMENT_EXPIRY`: "En insurance eppo expire aagum?", "என் இன்சூரன்ஸ் எப்போ முடியும்?", "When does my insurance expire?"
  - `LIST_DOCUMENTS`: "Enna documents irukku?", "Show my vehicle documents."
  - `CHECK_UNPAID_CHALLANS`: "Enakku unpaid challan irukka?", "எனக்கு டிராஃபிக் ஃபைன் அல்லது சலான் இருக்கா?"
  - `CHECK_UPCOMING_SERVICE`: "En auto ku service eppo?", "என் வண்டிக்கு சர்வீஸ் எப்போது?"
  - `RECORD_EXPENSE` / `ADD_MAINTENANCE`: "Auto service ku 1200 rooba selavu aachu."
- **Localized Voice Prompts (`app.agent.prompts`):** Context-aware Tamil, Tanglish, and English voice synthesis scripts generated for every Phase 5 intent.

---

## 3. Database Indexes

Database indexes were provisioned across 4 new collections in `app.database.indexes`:

| Collection | Index Fields | Purpose |
|---|---|---|
| `vehicle_documents` | `[("driver_id", 1), ("is_active", 1)]` | Active document vault lookup |
| `vehicle_documents` | `[("vehicle_id", 1), ("document_type", 1)]` | Vehicle-specific document queries |
| `vehicle_documents` | `[("expiry_date", 1)]` | Efficient batch expiry scans |
| `vehicle_reminders` | `[("idempotency_key", 1)]` (Unique) | Idempotent reminder generation |
| `vehicle_reminders` | `[("driver_id", 1), ("status", 1)]` | Driver pending reminder retrieval |
| `challans` | `[("driver_id", 1), ("status", 1)]` | Unpaid challan lookups |
| `challans` | `[("challan_number", 1)]` (Unique) | Duplicate challan prevention |
| `maintenance_records` | `[("driver_id", 1), ("vehicle_id", 1)]` | Vehicle service history queries |
| `maintenance_records` | `[("service_date", -1)]` | Historical maintenance chronology |

---

## 4. Automated Test Suite Results

The full test suite was executed in the project virtual environment (`backend/.venv`):

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests -v
```

### Summary:
- **Total Tests:** 184
- **Passed:** 183
- **Skipped:** 1 (`test_live_mongodb.py` — requires live cloud MongoDB cluster connection, skipped as intended)
- **Failed:** 0
- **Regressions:** 0 across all Phase 1–4 suites!

### Phase 5 Test Coverage:
1. `backend/tests/unit/test_vehicle_documents.py`: Document types, masking, expiry status calculations, document superseding, driver isolation.
2. `backend/tests/unit/test_document_storage.py`: Magic byte checks, file size constraints, traversal attacks, safe deletion.
3. `backend/tests/unit/test_expiry_reminders.py`: 30, 15, 7, 1, 0 day threshold calculations, idempotent duplicate prevention, notification delivery.
4. `backend/tests/unit/test_challan_service.py`: Status transitions, Decimal fine calculations, mock OCR preview with untrusted tagging.
5. `backend/tests/unit/test_maintenance_service.py`: Service intervals, maintenance logging, spending aggregation.
6. `backend/tests/unit/test_maintenance_financial_integration.py`: End-to-end confirmation firewall journey, idempotent retry safety, daily summary reflection.
7. `backend/tests/unit/test_phase5_agent_nlu.py`: Multilingual NLU intent parsing across Tamil script, Tanglish, and English.
8. `backend/tests/api/test_documents_api.py`: REST API endpoints for document creation, multipart upload, file download, compliance summary.
9. `backend/tests/api/test_challans_api.py`: REST API endpoints for challan addition, payment recording, OCR preview, driver isolation.
10. `backend/tests/api/test_maintenance_api.py`: Standalone and financial proposal endpoints, upcoming service queries.
11. `backend/tests/api/test_reminders_api.py`: Scan and acknowledgement API endpoints.
12. `backend/tests/api/test_phase5_voice_agent_api.py`: Complete conversational journeys for document checks, challans, service schedules, and voice maintenance confirmation.

---

## 5. Security & Verification Summary

1. **Authentication & Authorization:** All Phase 5 API endpoints enforce JWT authentication via `@require_auth`. All queries filter strictly by `driver_id` extracted from the cryptographically verified token claims. Cross-driver document/challan access attempts return HTTP 403 or 404.
2. **Path Traversal Defense:** Uploaded documents are saved under random UUID/hex keys within the storage adapter. File names are never concatenated directly into filesystem paths.
3. **Magic-Byte MIME Verification:** Extension spoofing (e.g. renaming `.exe` to `.pdf`) is blocked by verifying the file's binary header signatures.
4. **Append-Only Ledger Integrity:** Financial transactions resulting from vehicle maintenance cannot be edited or deleted once committed.
5. **Driver Confirmation Firewall:** No OCR capture or maintenance cost can write directly to the financial ledger without explicit driver approval.
