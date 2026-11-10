# T2T DRIVE — Phase 2: Tanglish Financial NLU & Transaction Safety Validation Report

**Report Date:** 2026-11-10T11:15:00+05:30  
**Phase:** Phase 2 Financial Safety, NLU & Multi-Transaction Confirmation Validation  
**Target Transcript:** `"இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."`  
**STT Provider Mode:** Offline Validation (Live STT previously verified; zero new live API calls made)  
**Ledger / DB Environment:** Isolated Test Database (Mongomock / Test Fixtures; zero production data accessed)  
**Overall Validation Status:** **`100% PASSED (294/294 Test Suite Pass Rate)`**

---

## 1. Existing Architecture Reused

The implementation reuses the existing T2T-DRIVE modular architecture without duplicate services, bypasses, or parallel engines:

- **NLU Engine:** [`backend/app/agent/nlu.py`](file:///d:/T2T%20DRIVE/backend/app/agent/nlu.py) (`MultilingualNLU`, `AgentIntent`)
- **Conversational State Machine:** [`backend/app/agent/graph.py`](file:///d:/T2T%20DRIVE/backend/app/agent/graph.py) (LangGraph `StateGraph`)
- **Node Handlers & Prompts:** [`backend/app/agent/nodes.py`](file:///d:/T2T%20DRIVE/backend/app/agent/nodes.py) & [`backend/app/agent/prompts.py`](file:///d:/T2T%20DRIVE/backend/app/agent/prompts.py)
- **Confirmation Firewall:** [`backend/app/services/pending_action_service.py`](file:///d:/T2T%20DRIVE/backend/app/services/pending_action_service.py) (`PendingActionService`)
- **Immutable Append-Only Ledger:** [`backend/app/services/ledger_service.py`](file:///d:/T2T%20DRIVE/backend/app/services/ledger_service.py) & [`backend/app/repositories/transaction_repository.py`](file:///d:/T2T%20DRIVE/backend/app/repositories/transaction_repository.py)
- **Financial Domain Models:** [`backend/app/models/financial.py`](file:///d:/T2T%20DRIVE/backend/app/models/financial.py) (`FinancialTransaction`, `PendingAction`, `TransactionType`, `quantize_money`)
- **Session & Voice Services:** [`backend/app/agent/service.py`](file:///d:/T2T%20DRIVE/backend/app/agent/service.py) & [`backend/app/voice/voice_service.py`](file:///d:/T2T%20DRIVE/backend/app/voice/voice_service.py)

---

## 2. Raw Transcript & Extracted Structured Entities

### Offline Input Transcript
```text
"இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."
```

### Extracted Structured Output
```json
{
  "intent": "RECORD_BATCH_TRANSACTIONS",
  "confidence": 0.96,
  "language": "tamil",
  "slots": {
    "transactions": [
      {
        "action_type": "ADD_INCOME",
        "category": "FARE",
        "amount": 1500.0,
        "description": "Collection ₹1500"
      },
      {
        "action_type": "ADD_EXPENSE",
        "category": "FUEL",
        "amount": 300.0,
        "description": "FUEL ₹300"
      },
      {
        "action_type": "ADD_OWNER_PAYMENT",
        "category": "OWNER_RENT",
        "amount": 200.0,
        "description": "Owner payment ₹200"
      }
    ],
    "vehicle_id": "DEFAULT_VEHICLE",
    "notes": "இன்னிக்கு collection 1500, petrol 300, owner-க்கு 200 கொடுத்தேன்."
  },
  "missing_slots": []
}
```

---

## 3. Financial Category Identification & Classification

All three financial transaction categories were independently and accurately identified:

| Spoken Segment | Target Financial Semantic | Extracted Category | Extracted Action Type | Extracted Amount | Mathematical Signed Amount |
|---|---|---|---|---:|---:|
| `"collection 1500"` | Daily FARE Income | **`FARE`** | **`ADD_INCOME`** | **`₹1,500.00`** | **`+1500.00`** |
| `"petrol 300"` | Operating Fuel Expense | **`FUEL`** | **`ADD_EXPENSE`** | **`₹300.00`** | **`-300.00`** |
| `"owner-க்கு 200 கொடுத்தேன்"` | Owner Rent Settlement | **`OWNER_RENT`** | **`ADD_OWNER_PAYMENT`** | **`₹200.00`** | **`-200.00`** |

### Key Fixes Applied to NLU
1. **Summary Query Collision Resolved:** Bare `"collection"` was previously in `SUMMARY_TERMS`, causing `"collection 1500"` to get prematurely hijacked into `GET_SUMMARY`. Refined `SUMMARY_TERMS` to query phrases (`"collection enna"`, `"collection evvalavu"`) and prioritized transaction extraction when numeric amounts are present.
2. **Compound Multi-Transaction Extraction:** Added `extract_multi_transactions()` to `MultilingualNLU`. It splits compound statements by punctuation (`[,;]`) or conjunctions (`and`, `apram`), matches domain keywords against corresponding categories, and extracts individual transactions.
3. **Intent Generalization:** Added `AgentIntent.RECORD_BATCH_TRANSACTIONS` to support atomic multi-transaction conversational proposals.

---

## 4. Confirmation Behavior & Safety Validation

The assistant enforces the **Confirmation Firewall**: no financial write is ever committed to the ledger without an explicit driver confirmation.

### A. Confirmation Proposal Presentation
When the transcript is received, the assistant generates a unified proposal:
- **English:** `"You earned ₹1,500.00 from collection, spent ₹300.00 on fuel, and paid ₹200.00 to the owner. Shall I save these transactions? Reply 'Confirm' or 'Cancel'."`
- **Tamil:** `"நீங்கள் கலெக்ஷனில் ₹1,500.00 வரவு, பெட்ரோலுக்கு ₹300.00 செலவு, மற்றும் ஓனருக்கு ₹200.00 செலுத்தப்பட்டுள்ளது. இந்த பதிவுகளை சேமிக்கவா? 'ஆம்' அல்லது 'வேண்டாம்' என்று கூறவும்."`
- **Tanglish:** `"Neenga collection-il ₹1,500.00 varavu, petrol-kku ₹300.00 selavu, matrum owner-kku ₹200.00 kudutheergal. Indha transactions-ai save seiyalama? 'Confirm' or 'Cancel' nu sollunga."`

### B. Tested Confirmation Scenarios

| Scenario | Driver Input | Behavior | Ledger Result | Test Status |
|---|---|---|---|---|
| **1. Full Confirmation** | `"ஆம்"` / `"confirm"` | Confirms all 3 proposed items. | Exactly 3 transactions written (`+1500`, `-300`, `-200`). Net: `+1000.00`. | **PASSED [✓]** |
| **2. Rejection** | `"வேண்டாம்"` / `"cancel"` | Cancels pending action (`CANCELLED`). | Strictly 0 transactions written. Pending action cannot be re-executed. | **PASSED [✓]** |
| **3. Ambiguous Confirmation** | `"maybe"` / `"what"` | Detects ambiguous answer; asks for clarification (`CLARIFY_CONFIRMATION`). | 0 transactions written. Pending action remains `PENDING`. | **PASSED [✓]** |
| **4. Partial Confirmation** | `"only petrol"` / `"petrol mattum"` | Detects filter; executes only the matching item (`filter_category="FUEL"`). | Exactly 1 transaction written (`FUEL: -300.00`). Other 2 omitted. | **PASSED [✓]** |
| **5. Duplicate Confirmation** | Repeat `"confirm"` | Idempotency guard returns cached `execution_result` immediately. | Exactly 3 transactions in total (zero duplicates). | **PASSED [✓]** |
| **6. Missing Amounts** | `"petrol and collection"` | Detects missing numbers -> routes to `slot_filling`. | Prompts driver for amount; 0 ledger writes. | **PASSED [✓]** |

---

## 5. Ledger Integrity & Isolation Results

- **Strict Monetary Types:** Every transaction enforces `quantize_money()` with Decimal 2-decimal-place precision. Floats are rejected.
- **Signed Amount Invariants:** Verified that `FinancialTransaction` mathematically asserts:
  - `INCOME`: `signed_amount == +amount`
  - `EXPENSE`: `signed_amount == -amount`
  - `OWNER_PAYMENT`: `signed_amount == -amount`
- **Owner Settlement Impact:** Verified that owner payment of ₹200 directly offsets the owner rent obligation in settlement calculations.
- **Driver Ownership Isolation:** Verified that Driver B cannot confirm, read, or manipulate Driver A's pending action (raises `PendingActionUnauthorizedError`).
- **Append-Only Immutability:** No transaction record is ever modified or deleted.

---

## 6. Test Suite Results

- **New Focused Test Suite:** [`backend/tests/unit/test_tanglish_nlu_and_safety.py`](file:///d:/T2T%20DRIVE/backend/tests/unit/test_tanglish_nlu_and_safety.py)
  - **12/12 Tests PASSED** (0 failures, 1.34s)
- **Full Regression Test Suite:**
  - **Total Collected Items:** 295
  - **PASSED:** **294**
  - **SKIPPED:** **1** (`test_live_mongodb.py` when live MongoDB Atlas URI is unconfigured)
  - **FAILED:** **0**
  - **Execution Time:** **8.07 seconds**

---

## 7. Files Changed

1. [`backend/app/models/financial.py`](file:///d:/T2T%20DRIVE/backend/app/models/financial.py): Added `ADD_BATCH_TRANSACTIONS` to `PendingActionType`.
2. [`backend/app/agent/nlu.py`](file:///d:/T2T%20DRIVE/backend/app/agent/nlu.py): Added `RECORD_BATCH_TRANSACTIONS` and `CLARIFY_CONFIRMATION` to `AgentIntent`, added `extract_multi_transactions()`, refined `SUMMARY_TERMS`, added partial confirmation and ambiguity detection.
3. [`backend/app/agent/prompts.py`](file:///d:/T2T%20DRIVE/backend/app/agent/prompts.py): Added `prompt_batch_proposal_confirmation()`, `prompt_batch_execution_success()`, `prompt_partial_execution_success()`, and `prompt_clarify_confirmation()`.
4. [`backend/app/agent/nodes.py`](file:///d:/T2T%20DRIVE/backend/app/agent/nodes.py): Added batch proposal and partial execution support in `action_proposal_node` and `action_execution_node`, added `clarify_confirmation_node`.
5. [`backend/app/agent/graph.py`](file:///d:/T2T%20DRIVE/backend/app/agent/graph.py): Registered `clarify_confirmation` node, updated conditional edges and transitions.
6. [`backend/app/services/pending_action_service.py`](file:///d:/T2T%20DRIVE/backend/app/services/pending_action_service.py): Added atomic batch execution, crash recovery lookup, summary generation, and partial filter execution in `confirm_action()`.
7. [`backend/tests/unit/test_tanglish_nlu_and_safety.py`](file:///d:/T2T%20DRIVE/backend/tests/unit/test_tanglish_nlu_and_safety.py): Added 12 new comprehensive tests.
