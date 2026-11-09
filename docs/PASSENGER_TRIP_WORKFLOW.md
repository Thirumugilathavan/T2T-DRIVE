# T2T DRIVE — Passenger Trip Agreement & Reconciliation Workflow
## End-to-End Operational Lifecycle Guide

### 1. Overview
The T2T DRIVE Passenger Extension bridges the commercial divide between the driver (primary smartphone user) and the passenger (lightweight, zero-install mobile web participant).

This document details the step-by-step state transitions, cryptographic handshakes, mutual confirmation firewall rules, and financial ledger interactions that occur throughout a trip.

---

### 2. End-to-End Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Driver as Auto Driver
    participant DApp as Driver App (T2T DRIVE)
    participant Server as T2T Backend (Flask + LangGraph)
    actor Passenger as Passenger (Smartphone)
    participant Ledger as Append-Only Ledger

    %% 1. Trip Creation
    Driver->>DApp: Voice: "Central Station fare 200"
    DApp->>Server: POST /api/trips
    Server->>Server: Generate Trip ID + Secret Token + SVG QR
    Server-->>DApp: Return Trip (AGREEMENT_PENDING) + QR SVG
    DApp->>Driver: Display Dynamic In-Cabin QR Code

    %% 2. Passenger Access & Initial Agreement
    Passenger->>DApp: Scans In-Cabin QR Code
    Passenger->>Server: GET /api/passenger/trips/:id?token=:token
    Server-->>Passenger: Render Privacy-Preserved Trip View
    Passenger->>Server: POST /agreement { accepted: true }
    Server->>Server: Upgrade State to AGREED (Version 1)
    Server-->>DApp: Real-time update: Passenger Agreed
    Driver->>DApp: Tap / Voice: "Start Trip"
    DApp->>Server: POST /trips/:id/start (State: IN_PROGRESS)

    %% 3. In-Trip Mid-Route Modification
    Note over Driver, Passenger: Driving in City Traffic...
    Driver->>DApp: Voice: "Add stop at Apollo Pharmacy"
    DApp->>Server: POST /trips/:id/propose-change (ADD_STOP)
    Server-->>Passenger: Real-time Push / Polling Notice: Proposal Pending
    Passenger->>Server: POST /respond-proposal { accepted: true }
    Server->>Server: Mutual Agreement Achieved! Bump to Version 2
    Server-->>DApp: Voice Audio: "Stop confirmed by passenger."

    %% 4. Fare Collection & Reconciliation
    Passenger->>Driver: Pays ₹200 via UPI / Cash
    Driver->>DApp: Voice / Tap: "Collect ₹200 UPI"
    DApp->>Server: POST /trips/:id/payments (Idempotency Key)
    Server->>Ledger: Append Transaction (Category: TRIP_FARE, Income: ₹200)
    Server->>Server: Update Trip (Collected: ₹200, Outstanding: ₹0.00, PAID)
    Server-->>DApp: Audio: "Fare payment recorded."

    %% 5. Completion & Token Revocation
    Driver->>DApp: Tap / Voice: "Complete Trip"
    DApp->>Server: POST /trips/:id/complete (State: COMPLETED)
    Server->>Server: Halt Continuous Listening & Revoke Token
    Passenger->>Server: GET /receipt (View Final Shared Digital Receipt)
    Server-->>Passenger: Render Tamper-Evident Receipt
```

---

### 3. State Transition Matrix

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> AGREEMENT_PENDING: Driver specifies destination & initial fare
    
    AGREEMENT_PENDING --> AGREED: Passenger accepts initial fare (Version 1)
    AGREEMENT_PENDING --> CANCELLED: Passenger declines fare OR driver cancels

    AGREED --> IN_PROGRESS: Driver initiates journey
    AGREED --> CANCELLED: Pre-departure cancellation

    IN_PROGRESS --> CHANGE_PENDING: Either party proposes destination/stop/fare change
    CHANGE_PENDING --> IN_PROGRESS: Dual acceptance (Version upgraded) OR rejection (Version retained)

    IN_PROGRESS --> COMPLETED: Journey finishes, destination reached
    IN_PROGRESS --> DISPUTED: Fare or route discrepancy logged

    DISPUTED --> COMPLETED: Settled post-trip
    COMPLETED --> [*]
    CANCELLED --> [*]
```

---

### 4. Step-by-Step Lifecycle Phases

#### Phase A: Trip Initiation & In-Cabin QR Presentation
1. **Trigger:** Driver arrives at pickup or street hail. Driver says: `"Anna Nagar roundtana, fare 220"`.
2. **Backend Action:** `POST /api/trips` executes.
   - Generates unique `TRIP_XXXXXXXX`.
   - Generates 256-bit entropy token via `secrets.token_urlsafe(32)`.
   - Computes keyed HMAC-SHA-256 hash and stores in `trip_passenger_access`.
   - Generates clean, zero-network inline SVG QR code embedding URL:
     `https://<domain>/passenger.html?trip_id=TRIP_XXXX&token=YYYY`
3. **Display:** Driver dashboard renders QR code on windshield/partition phone mount.

#### Phase B: Passenger Onboarding (Zero App Installation)
1. **Passenger Action:** Points smartphone camera (iOS Camera or Android Google Lens) at the QR code.
2. **No App Barrier:** The browser opens directly into `frontend/passenger.html`.
3. **Data-Minimization Filter:** The backend serves ONLY passenger-relevant fields:
   - Vehicle registration number (`TN-01-AB-1234`).
   - Pickup & Destination locations.
   - Proposed Fare (`₹220.00`).
   - *Driver personal phone, cumulative daily earnings, and owner settlements are completely stripped.*

#### Phase C: Initial Agreement (v1)
1. **Acceptance:** Passenger taps **"Agree to Fare & Destination"**.
2. **Transition:** State shifts from `AGREEMENT_PENDING` to `AGREED`.
3. **Version Stamp:** Agreement Version 1 is created:
   ```json
   {
     "version": 1,
     "pickup_location": "Central",
     "destination_location": "Anna Nagar",
     "additional_stops": [],
     "agreed_fare": "220.00",
     "agreed_at": "2026-11-09T07:15:00Z"
   }
   ```
4. **Driver Start:** Driver taps **"Start Trip"** (or says *"Trip start pannu"*); state shifts to `IN_PROGRESS`.

#### Phase D: Mid-Trip Route Modification & Confirmation Firewall
1. **Trigger:** Passenger asks to divert to buy medicines: *"Vazhila Apollo Pharmacy-la konjam niruthunga"*.
2. **Voice Event Detection:** `TripEventClassifier` detects `POSSIBLE_ADD_STOP` with high confidence (`0.84`).
3. **Proposal Creation:**
   - Proposer: `PASSENGER` (or `DRIVER`).
   - State shifts to `CHANGE_PENDING`.
   - `active_proposal` document created.
4. **Dual Acceptance Requirement:**
   - Proposing party is marked accepted.
   - Opposing party receives an audio/screen prompt: *"Additional stop proposed: Apollo Pharmacy. Confirm?"*
   - Opposing party must explicitly confirm (`respond-proposal { accepted: true }`).
5. **Version Upgrade:**
   - Upon dual confirmation, Agreement Version increments to `v2`.
   - `v1` is permanently appended to `agreement_history`.
   - If either party declines, `active_proposal` is cleared, and active parameters remain on `v1`.

#### Phase E: Continuous Listening Consent Lifecycle
1. **Default State:** Continuous listening is strictly **OFF**.
2. **Independent Affirmative Consent:**
   - Driver must explicitly toggle consent ON.
   - Passenger must explicitly tap consent ON on their device.
3. **Immediate Revocation Purge:**
   - The instant either party withdraws consent, the server halts streaming STT, flushes RAM ring buffers, and logs a `CONSENT_UPDATED` audit record.

#### Phase F: Financial Reconciliation & Idempotency
1. **Three-Tier Accounting Isolation:**
   - **Earned Fare:** The agreed fare (`₹220.00`).
   - **Collected Amount:** Sum of verified cash/UPI payments recorded on this trip.
   - **Outstanding Balance:** `Earned Fare - Collected Amount`.
2. **Idempotent Ledger Entry:**
   - When driver records payment, `IdempotencyService` locks `idempotency_key`.
   - Appends single immutable transaction to ledger: `transaction_type="INCOME"`, `category="TRIP_FARE"`.
   - Vehicle owner rental settlement math remains unaffected and completely accurate.

#### Phase G: Trip Completion, Receipt & Token Revocation
1. **Completion:** Driver reaches destination and completes trip.
2. **Security Lockdown:**
   - Passenger token is immediately revoked in `trip_passenger_access`.
   - Continuous audio session is killed.
3. **Receipt Generation:**
   - Passenger accesses final transparent digital receipt at `/receipt`.
   - Displays complete version history, payments breakdown, and dispute hotline info.
