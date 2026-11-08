# T2T DRIVE — Noise-Aware, Multilingual AI Voice Co-Pilot for Auto-Rickshaw and Cab Drivers

> **Tagline:** Speak Naturally. Manage Intelligently. Drive Smarter.  
> **Tech Stack:** HTML5, CSS3, Vanilla JavaScript (ES6+). Zero external frameworks.

---

## 1. Overview

**T2T DRIVE** is a purpose-built, high-contrast, driver-first dashboard application designed for auto-rickshaw and cab drivers across India. It enables seamless daily operational management via multilingual voice and tactile interactions in **Tamil**, **Tanglish**, and **English**.

### Key Highlights
* **Zero Audio Interruption (SPA Architecture):** Hash-based routing preserves active microphone audio streams and speech recognition sessions across views.
* **Driver-First Cockpit Ergonomics:** High-contrast OLED dark mode (reduces eye fatigue during night driving) with 48px+ touch targets optimized for mounted phones on dashboard/windshields.
* **Ambient Noise-Aware Voice Input:** Live Web Audio API waveform visualizer and acoustic profile tailored for noisy road environments (filtering 120Hz-400Hz engine hum).
* **Smart Financial Extraction & Confirmation:** Instant parsing of multi-part driver utterances (e.g., *"Inniku collection 1500, petrol 300, owner-ku 200 kuduthen"*) with large tactile Yes/No confirmation cards before committing transactions.
* **Zero External JS Dependencies:** Pure Vanilla HTML5/CSS3/JavaScript with native Canvas charts and Web Audio synthesizers.

---

## 2. Directory Structure

```text
frontend/
│
├── index.html                  # Master single-page application shell hosting all 6 sections
│
├── css/
│   ├── style.css               # Core cockpit design tokens, themes, buttons, cards, visualizers
│   └── responsive.css          # Mobile-first breakpoints (phone mounts, tablets, desktop)
│
├── js/
│   ├── app.js                  # Master boot controller, theme toggle, toast hub, error boundary
│   ├── navigation.js           # Hash-router, mobile drawer, shortcuts (Alt+1 to 6), Command Palette (Cmd+K)
│   ├── api.js                  # Reusable Fetch API service with configurable base URL
│   ├── mock-api.js             # Offline Indic speech & NLU simulator with '_mock: true' tags
│   ├── voice.js                # Push-to-talk (PTT), Web Audio analyser, audio file upload, confirmation flow
│   ├── finance.js              # KPI counters, vanilla canvas bar/donut charts, ledger filters
│   ├── documents.js            # Glovebox document manager, days-left countdown, expiry alerts
│   ├── settlement.js           # Owner reconciliation calculator, variance indicator, ledger
│   ├── vehicle.js              # Vehicle maintenance tracker, service interval telemetry
│   └── agent.js                # AI reasoning trace, Indic-ASR & NLU slot inspector, noise evaluation
│
├── assets/
│   ├── icons/                  # SVG assets
│   └── images/                 # App branding & avatar assets
│
└── README.md                   # Complete architectural guide and running instructions
```

---

## 3. The Six Dashboard Sections

1. **🎙️ Voice Co-Pilot (Home):**
   * Centered Push-To-Talk (PTT) microphone with pulse rings and live audio visualizer.
   * Language selector: Tamil, Tanglish, English.
   * Editable speech transcript and detected language pill.
   * Transaction confirmation card with color-coded entity chips:
     * 🟢 Income (Collection)
     * 🔴 Expense (Fuel/Diesel/Tea)
     * 🟡 Owner Payment (Bhatta)
     * 🔵 Net Margin
   * Tactile Yes/No confirmation buttons.
   * Native audio player for AI voice feedback.
   * Conversation timeline and quick sample prompt chips.

2. **💰 Finance Dashboard:**
   * Today's Income, Expenses, Owner Bhatta, and Net Take-Home Balance.
   * Period toggles: `Today`, `Weekly`, and `Monthly`.
   * Vanilla HTML5 Canvas Bar Chart comparing Daily Income vs Expenses.
   * Vanilla HTML5 Canvas Donut Chart for Expense Category breakdown.
   * Searchable transaction ledger with filter pills (`All`, `Income`, `Expense`, `Owner`).

3. **📑 Documents Vault:**
   * 5 commercial vehicle documents: Driving Licence, Insurance, Permit, Fitness Certificate (FC), and PUC.
   * Real-time days-to-expire countdowns.
   * Dynamic color-coded status badges:
     * 🔴 *Critical Alert:* `< 7 days` or Expired
     * 🟡 *Renewal Warning:* `< 30 days`
     * 🟢 *Valid:* `> 30 days`
   * Modal dialog for registering new documents.
   * Motor Vehicles Act penalty guidance.

4. **🤝 Owner-Driver Settlement:**
   * Daily reconciliation calculator: `Driver Collection` vs `Owner Daily Rent/Target`.
   * Automatic variance calculation with instant badges:
     * 🟢 `MATCHED` (No dues on either side)
     * 🟡 `DRIVER SURPLUS` (Driver paid advance)
     * 🔴 `DUE TO OWNER` (Pending arrears)
   * Owner profile card with contact and agreed contract rates.
   * Daily settlement history ledger.

5. **🛺 Vehicle Health & Maintenance:**
   * Auto telemetry card (Bajaj RE Compact 4S, Odometer, Reg: TN-09 CB 1284).
   * Preventive maintenance schedule progress bars (Engine oil, brakes, spark plug, clutch).
   * Log service form that automatically records costs and syncs with the Finance ledger.
   * Historical garage repair logs.

6. **🧠 Agent & AI Diagnostic Console:**
   * Real-time 6-step pipeline telemetry visualizer:
     1. Acoustic Noise Gate (120Hz-400Hz filter)
     2. Speech Recognition (Gnani Indic-ASR)
     3. Language Classification
     4. NLU Intent Parsing
     5. Slot Filling & Entity Extraction
     6. Driver Confirmation Gate
   * Live JSON slot inspector.
   * Acoustic cabin noise profile and SNR meter (24.2 dB).

---

## 4. How to Run Locally

Because the application uses modern browser Web Audio and `MediaRecorder` APIs, it is best served over a local HTTP server:

```bash
# Navigate to the frontend directory
cd d:/tharana/anti-gravity/frontend

# Start Python's built-in HTTP server
python -m http.server 5500
```

Open your browser at:
```
http://localhost:5500
```

---

## 5. API Endpoints & Mode Configuration

### Centralized Config (`js/api.js`)
```javascript
window.T2T_CONFIG = {
  MODE: "mock",                      // Toggle between "mock" and "live"
  API_BASE: "http://localhost:8000", // FastAPI backend address
  ENDPOINTS: {
    transcribe:        "/api/speech/transcribe",
    agentMessage:      "/api/agent/message",
    agentConfirm:      "/api/agent/confirm",
    financeSummary:    "/api/finance/summary",
    documents:         "/api/documents",
    settlementCompare: "/api/settlement/compare",
    speak:             "/api/speech/speak"
  }
};
```

* **Toggle via UI:** Tap the **"Switch to Live"** button in the sidebar footer anytime to toggle modes without page refresh.
* **Mock Mode Guarantee:** All simulated mock responses return `_mock: true` and clearly indicate that data is stored in browser memory only without false database persistence claims.

