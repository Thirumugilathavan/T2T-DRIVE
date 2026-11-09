# T2T DRIVE — Passenger Extension Architecture Audit
**Audit Date:** November 9, 2026  
**Repository:** https://github.com/Thirumugilathavan/T2T-DRIVE  
**Baseline Test Status:** 221 Passed, 1 Skipped, 0 Failed (Pytest 8.2.2, Python 3.14.7)  
**Author:** Principal Software Architect & Application Security Reviewer  

---

## 1. Executive Summary & Purpose

T2T DRIVE has successfully completed Phases 1 through 6, establishing:
1. Hardened driver authentication with HMAC-SHA-256 OTP verification and JWT session control.
2. An append-only immutable financial ledger with multi-shift vehicle settlements and crash-recoverable idempotency.
3. A multi-turn LangGraph conversational agent supporting Tamil, Tanglish, and English with strict Confirmation Firewall protection.
4. Gnani Prisma STT and Timbre TTS voice adapters.
5. Document management, expiry tracking, challan tracking, and vehicle maintenance logging.
6. Advanced noise-aware speech intelligence, adaptive high-pass filtering (120 Hz), peak-safe normalization, VAD, and benchmarking.

This audit evaluates the codebase before extending T2T DRIVE to support **Passenger-Aware Trip Agreements, Consent-Based Continuous Listening, Mutual Change Confirmations, and Financial Trip Reconciliation**.

The objective is strictly **incremental extension**:
- Zero destruction or unnecessary refactoring of Phases 1–6.
- Maximum reuse of the existing append-only ledger, idempotency service, LangGraph agent, and noise engine.
- Preservation of the 221 existing passing tests.

---

## 2. Existing Architecture & Baseline Inventory

### 2.1 Backend Architecture Overview
- **Framework:** Python Flask (Application Factory pattern in `backend/app/__init__.py`).
- **Database:** MongoDB Atlas via PyMongo (with `mongomock` test harness). 13 production collections configured in `backend/app/database/indexes.py`.
- **Validation:** Pydantic v2 domain schemas (`backend/app/models/`).
- **Monetary Representation:** Python `Decimal` quantized to 2 decimal places (`Decimal("0.01")`), stored in MongoDB as `Decimal128` (IEEE 754-2008).
- **Conversational AI:** LangGraph StateGraph (`backend/app/agent/graph.py`) orchestrated by `AgentService` (`backend/app/agent/service.py`) and ruled by `AgentNodes` (`backend/app/agent/nodes.py`).
- **Speech Pipeline:** `VoiceService` (`backend/app/voice/voice_service.py`), `NoiseService` (`backend/app/voice/noise/noise_service.py`), `PrismaAdapter` (`backend/app/voice/prisma_adapter.py`), and `TimbreAdapter` (`backend/app/voice/timbre_adapter.py`).

### 2.2 Existing Features Ready for Direct Reuse
| Component | Existing File | Reusable Capabilities |
|:---|:---|:---|
| **Ledger Engine** | `app/services/ledger_service.py` | Immutable append-only ledger (`record_transaction`), audited adjustments (`create_adjustment`), and reversals (`create_reversal`). |
| **Transaction Repository** | `app/repositories/transaction_repository.py` | BSON `Decimal128` serialization/deserialization, transaction queries, and driver balance lookups. |
| **Idempotency Service** | `app/services/idempotency_service.py` | Atomic lock acquisition (`acquire_key`), caching, and idempotent replay across retried payments or trip actions. |
| **Pending Action Boundary** | `app/services/pending_action_service.py` | Crash-recoverable `PENDING_ACTION` lifecycle ensuring no financial write occurs without explicit confirmation. |
| **Financial Calculator** | `app/services/financial_calculator.py` | Signed amount calculations and settlement balance aggregation. |
| **Summary Service** | `app/services/summary_service.py` | Daily, weekly, and monthly metric rollups across income, expenses, and net earnings. |
| **Settlement Service** | `app/services/settlement_service.py` | Owner-driver vehicle rental reconciliation, carry-forward deficit tracking, and versioned settlements. |
| **NLU & Intent Extraction** | `app/agent/nlu.py` | Multilingual number parsing (Tamil, Tanglish, English digits/words), category matching, and entity extraction. |
| **LangGraph Agent Workflow** | `app/agent/graph.py` | State-machine routing (`interpret` -> `slot_filling` -> `confirmation` -> `execution`). |
| **Noise Intelligence Engine** | `app/voice/noise/` | Acoustic metrics, SNR estimation, 10-class noise classification, VAD, 120Hz high-pass filter, and multi-dimensional confidence. |
| **Voice Adapters** | `app/voice/` | Prisma STT and Timbre TTS REST adapters with transparent mock fallbacks. |
| **Auth & Security** | `app/utils/decorators.py` | `require_auth` decorator verifying JWT claims (`driver_id`, `jti`, expiration). |

### 2.3 Existing Features Requiring Small Modifications
1. **`app/models/financial.py`:**
   - Add transaction sub-category or metadata tags for `TRIP_FARE_COLLECTED` to associate ledger income entries with a specific `trip_id`.
2. **`app/agent/nlu.py`:**
   - Add 5 essential trip intent definitions: `START_TRIP`, `CHANGE_DESTINATION`, `ADD_STOP`, `CHANGE_FARE`, and `RECORD_TRIP_PAYMENT`.
   - Add intent pattern extractors for trip locations ("new bus stand", "railway station", "petrol bunk") and fare change proposals without disrupting existing financial intents.
3. **`app/agent/nodes.py`:**
   - Connect trip intent handlers to the trip service and confirmation firewall.
4. **`app/voice/voice_service.py`:**
   - Provide an optional `trip_id` context parameter in `process_voice_turn` so spoken statements can be evaluated against an active trip state.
5. **`app/database/indexes.py`:**
   - Add index declarations for new `trips`, `trip_agreements`, `trip_events`, `trip_change_proposals`, and `trip_passenger_access` collections.

---

## 3. Gap Analysis: Missing Functionality to Implement

To support the passenger-aware extension, the following subsystems must be introduced:

### 3.1 Trip Lifecycle & Versioned Agreement Engine (`app/services/trip_service.py`)
- **Deterministic State Machine:** `CREATED` -> `AGREEMENT_PENDING` -> `AGREED` -> `IN_PROGRESS` -> `CHANGE_PENDING` -> `PAYMENT_PENDING` -> `COMPLETED` (or `CANCELLED` / `DISPUTED`).
- **Versioned Agreements:** Each accepted change bumps `agreement_version` (v1, v2, v3), preserving prior agreed fares, pickups, and destinations. Previous agreements are never overwritten.
- **Mutual Confirmation Workflow:** A change proposed by either party enters `PENDING` state and requires explicit acceptance from both parties before becoming active. Rejection or timeout preserves the prior agreed state.

### 3.2 Secure Temporary Passenger Access (`app/services/passenger_access_service.py`)
- **Access Tokens:** Cryptographically secure 256-bit random tokens (`secrets.token_urlsafe(32)`).
- **Hashed Storage:** Only the HMAC-SHA-256 hash of the passenger token is stored in the database.
- **Scoped Permissions:** Token is strictly bound to a single `trip_id`, with time-to-live (TTL), expiration check, and revocation capability.
- **Access URL & QR Code:** QR code generation (SVG / Canvas / pure Python generation) returning a temporary link (`/passenger.html?trip_id=...&token=...`).
- **Data Minimization:** Passenger access grants visibility only into trip details (pickup, destination, agreed fare, stops, payment status), completely shielding the driver's phone number, owner settlements, total earnings, and audit logs.

### 3.3 Passenger Financial Reconciliation (`app/services/trip_reconciliation_service.py`)
- **Earned vs. Collected Isolation:**
  - *Earned Fare:* Amount mutually agreed for the journey (e.g., ₹250.00).
  - *Collected Amount:* Amount received so far (e.g., ₹200.00).
  - *Outstanding Receivable:* `Earned - Collected` (e.g., ₹50.00).
  - *Subsequent Collection:* When the remaining ₹50.00 is collected, it settles the receivable without double-counting revenue.
- **Ledger Integration:** Integrates seamlessly with `LedgerService.record_transaction(..., category="TRIP_FARE")`, ensuring owner-driver vehicle settlement balances remain completely unaffected.

### 3.4 Consent-Based Continuous Listening & Audio Privacy
- **Strict Independent Consent:** Continuous listening is **OFF by default**. Both driver and passenger must independently click an affirmative consent button before any continuous stream is processed.
- **Immediate Revocation:** Either party can withdraw consent at any time; listening terminates immediately, buffers are wiped, and the system reverts to Push-to-Talk (PTT).
- **In-Memory Buffering:** Raw audio and ordinary conversational transcripts are **never saved to MongoDB**. Only structured, confirmed trip events (e.g., `CHANGE_DESTINATION`) are committed to database history.
- **Streaming STT Investigation:** Current Prisma integration is REST-based (`https://api.vachana.ai/stt/v3`). The streaming endpoint `wss://api.vachana.ai/stt/v3/stream` is unverified without authorized live credentials. A clean streaming adapter interface with an offline/mock streaming simulator and a placeholder live adapter will be implemented, clearly flagging mock status.

### 3.5 Driver Safety Interaction Policy (`docs/DRIVER_SAFETY_INTERACTION_POLICY.md`)
- Non-distracting, minimal voice notifications.
- No mandatory touchscreen interactions while vehicle is in motion.
- Passenger can review and accept proposals on their own mobile screen.

### 3.6 Lightweight Responsive Passenger Webpage (`frontend/passenger.html`)
- Standalone HTML5 / vanilla CSS / JS webpage requiring **zero app installation** and zero driver account creation.
- Displays trip details, proposed fare, agreement buttons ("Agree", "Decline", "Request Change"), continuous listening consent status, live payment summary, dispute flag, and digital trip receipt.

---

## 4. Integration & System Risks

| Risk Area | Severity | Impact | Mitigation Strategy |
|:---|:---:|:---|:---|
| **Ledger Double-Counting** | High | Partial payment followed by remainder collection could record inflated gross revenue. | Implement explicit `trip_payments` tracking. The ledger records initial collection; second collection records remainder under `reference_id=trip_id`. |
| **Owner Settlement Mixing** | Critical | Passenger fare disputes or receivables could distort owner rental balances. | Keep owner rental calculations strictly scoped to transaction ledger entries; trip receivables are driver-passenger balance sheets only. |
| **Cross-Trip Access Vulnerability** | High | Malicious passenger guessing trip IDs could view other passengers' trips. | Trip IDs are random UUIDs (`TRIP_...`), and access requires matching the hashed cryptographic secret token. Rate limiting is applied. |
| **Driving Distraction** | Critical | Driver operating phone screen while driving auto-rickshaw in traffic. | Voice-first or passenger-confirmed workflow. Driver screen interactions deferred until stationary. |
| **Unverified Streaming STT Endpoint** | Medium | Continuous streaming endpoint fails or lacks documentation. | Interface segregation: implement `StreamingSTTAdapterBase`, `MockStreamingSTTAdapter`, and unverified live adapter. Do not claim mock is live. |
| **Spurious Event False Positives** | High | Casual conversation ("It is hot, let's stop for tea") accidentally altering trip destination or fare. | Strict intent classification thresholds, context awareness, proposal creation requiring dual confirmation, and Confirmation Firewall. |

---

## 5. External Service Dependencies

1. **Gnani Prisma STT (REST):** Live credentials optional; verified mock adapter exists and passes all tests.
2. **Gnani Timbre TTS (REST):** Live credentials optional; verified mock adapter exists.
3. **Gnani Streaming STT (WebSocket):** Unverified. Will be implemented as an interface with `MockStreamingSTTAdapter` for offline testing.
4. **MongoDB Atlas / PyMongo:** Runs on local `mongomock` in tests and standard MongoDB in production.
5. **QR Code Generator:** Pure Python / client-side SVG generation to avoid external third-party API dependencies.

---

## 6. Incremental Implementation Plan

### Stage 1: Audit & Baseline (Completed)
- Document baseline architecture, reusable services, and risks in `docs/PASSENGER_EXTENSION_AUDIT.md`.
- Verify 221 existing tests pass.

### Stage 2: Trip Agreement Foundation
- Define Pydantic models in `backend/app/models/trip.py`: `Trip`, `TripAgreement`, `TripEvent`, `TripChangeProposal`, `PassengerAccess`, `TripPayment`.
- Create `TripRepository` and `TripService` managing state transitions and versioned agreements.
- Create `PassengerAccessService` generating cryptographically secure hashed access tokens.
- Add REST routes in `backend/app/routes/trip_routes.py` and `backend/app/routes/passenger_routes.py`.
- Build `frontend/passenger.html` and `frontend/js/passenger.js`.

### Stage 3: Trip Changes & Mutual Confirmation
- Implement proposal creation (`CHANGE_DESTINATION`, `ADD_STOP`, `CHANGE_FARE`).
- Implement dual-confirmation state machine: driver accept/reject, passenger accept/reject, timeout, and dispute.
- Author `docs/DRIVER_SAFETY_INTERACTION_POLICY.md`.

### Stage 4: Financial Reconciliation
- Connect trip payment completion to Phase 2 `LedgerService`.
- Model earned vs. collected amounts and outstanding receivables.
- Support Cash and recorded UPI with partial payment support and duplicate prevention.
- Implement passenger digital receipt endpoint.

### Stage 5: Multilingual Voice & Event Detection
- Extend `app/agent/nlu.py` with the 5 essential trip intents.
- Distinguish casual passenger conversation from actionable trip requests.
- Integrate confidence directives (`speech_confidence.py`).

### Stage 6: Consent-Based Continuous Listening
- Implement `TripAudioSession` with independent driver and passenger consent tracking.
- Create streaming STT adapter interface (`MockStreamingSTTAdapter` & unverified live adapter).
- Implement ephemeral in-memory audio buffers and auto-wipe on consent withdrawal.
- Author `docs/PRIVACY_AND_AUDIO_DATA_FLOW.md` and `docs/SPEECH_DATASET_AND_CONSENT_PROTOCOL.md`.

### Stage 7: Evaluation, Field Protocol & Testing
- Author `docs/FIELD_RESEARCH_PLAN.md` and `docs/COMPETITIVE_ANALYSIS.md`.
- Implement comprehensive automated test suite covering all 27 required trip scenarios.
- Run continuous listening false-alert evaluation.
- Compile `docs/PASSENGER_EXTENSION_TEST_REPORT.md` and `docs/PASSENGER_EXTENSION_COMPLETION_REPORT.md`.
- Verify zero regressions on baseline 221 tests.
