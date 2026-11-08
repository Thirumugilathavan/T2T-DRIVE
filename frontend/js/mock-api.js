/**
 * T2T DRIVE — MOCK API SERVICE
 * Offline Simulation Engine with realistic Indic speech/intent parsing.
 * Every response carries `_mock: true`.
 * Does NOT claim real backend or persistent database writes.
 */

(function () {
  'use strict';

  // Simulated network latency helper
  const delay = (ms = 500) => new Promise(resolve => setTimeout(resolve, ms));

  // In-memory mock database state
  const mockDB = {
    finance: {
      today: { income: 1500, expenses: 300, owner_payments: 200, net_balance: 1000 },
      weekly: { income: 10800, expenses: 2400, owner_payments: 1400, net_balance: 7000 },
      monthly: { income: 42500, expenses: 9800, owner_payments: 6000, net_balance: 26700 },
      category_breakdown: [
        { name: "Petrol / Diesel", value: 1400, color: "#ef4444" },
        { name: "Maintenance & Oil", value: 450, color: "#f59e0b" },
        { name: "Toll & Parking", value: 180, color: "#3b82f6" },
        { name: "Tea & Food", value: 170, color: "#10b981" },
        { name: "Other Misc", value: 200, color: "#8b5cf6" }
      ],
      weekly_days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
      income_series: [1400, 1650, 1300, 1550, 1700, 1800, 1500],
      expense_series: [280, 320, 310, 290, 420, 480, 300],
      transactions: [
        { id: "tx-1", date: "Today, 06:45 PM", type: "income", description: "Evening Central Station trips", amount: 650, mode: "Cash" },
        { id: "tx-2", date: "Today, 04:10 PM", type: "owner", description: "Owner Bhatta payout", amount: 200, mode: "UPI" },
        { id: "tx-3", date: "Today, 01:30 PM", type: "expense", description: "LPG / Petrol auto refuel", amount: 300, mode: "Cash" },
        { id: "tx-4", date: "Today, 11:15 AM", type: "income", description: "T.Nagar to Airport trip", amount: 550, mode: "GPay" },
        { id: "tx-5", date: "Today, 08:00 AM", type: "income", description: "Morning peak rides (3 trips)", amount: 300, mode: "Cash" },
        { id: "tx-6", date: "Yesterday", type: "income", description: "Total day rides", amount: 1800, mode: "Mixed" }
      ]
    },
    documents: [
      { id: "doc-1", type: "Driving Licence", number: "TN-09-2018-004821", expiry: "2028-10-14", days_left: 705, status: "safe" },
      { id: "doc-2", type: "Vehicle Insurance", number: "POL-ICICI-884219", expiry: "2026-11-28", days_left: 20, status: "warning" },
      { id: "doc-3", type: "Auto Permit", number: "PRM-CHENNAI-3921", expiry: "2027-04-10", days_left: 153, status: "safe" },
      { id: "doc-4", type: "Fitness Certificate", number: "FC-RTO09-91823", expiry: "2026-11-14", days_left: 6, status: "danger" },
      { id: "doc-5", type: "PUC (Pollution)", number: "PUC-EMISS-7721", expiry: "2027-01-15", days_left: 68, status: "safe" }
    ],
    settlement: {
      driver_collection: 1500,
      owner_expected: 500,
      driver_fuel: 300,
      amount_paid: 500,
      history: [
        { date: "08 Nov 2026", collection: 1500, quota: 500, paid: 500, diff: 0, status: "MATCHED" },
        { date: "07 Nov 2026", collection: 1800, quota: 500, paid: 500, diff: 0, status: "MATCHED" },
        { date: "06 Nov 2026", collection: 1400, quota: 500, paid: 400, diff: -100, status: "DUE_TO_OWNER" },
        { date: "05 Nov 2026", collection: 1950, quota: 500, paid: 600, diff: +100, status: "DRIVER_SURPLUS" },
        { date: "04 Nov 2026", collection: 1600, quota: 500, paid: 500, diff: 0, status: "MATCHED" }
      ]
    },
    vehicle: {
      reg_number: "TN-09 CB 1284",
      model: "Bajaj RE Compact 4S",
      odometer: 64280,
      schedule: [
        { title: "Engine Oil Replacement", dueKm: 65000, currentKm: 64280, dueInKm: 720, urgency: "warning" },
        { title: "Brake Liner & Drum Check", dueKm: 67000, currentKm: 64280, dueInKm: 2720, urgency: "safe" },
        { title: "Spark Plug & Carburetor Tune", dueKm: 66000, currentKm: 64280, dueInKm: 1720, urgency: "safe" },
        { title: "Clutch Cable Adjustment", dueKm: 64500, currentKm: 64280, dueInKm: 220, urgency: "danger" }
      ],
      maintenance_logs: [
        { date: "22 Oct 2026", type: "Engine Oil & Filter Change", garage: "Shanmugam Auto Works, T.Nagar", odo: "63,800 km", cost: 450 },
        { date: "10 Sep 2026", type: "Brake Shoe Replacement", garage: "Ramesh Auto Care, Vadapalani", odo: "62,100 km", cost: 380 },
        { date: "15 Jul 2026", type: "Tyre Replacement / Tube", garage: "MRF Tyres, Kodambakkam", odo: "59,400 km", cost: 1250 }
      ]
    }
  };

  /**
   * Mock Transcribe: Speech-to-text
   */
  async function transcribe(audioBlobOrFile, lang = "tanglish") {
    await delay(600);

    const transcriptsByLang = {
      tanglish: "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen.",
      ta: "இன்னிக்கு கலெக்ஷன் 1500, பெட்ரோல் 300, ஓனர்-க்கு 200 கொடுத்தேன்.",
      en: "Today collection 1500, petrol 300, gave 200 to owner."
    };

    const chosenTranscript = transcriptsByLang[lang] || transcriptsByLang.tanglish;

    return {
      transcript: chosenTranscript,
      detected_language: lang,
      confidence: 0.96,
      snr_db: 24.5,
      noise_filtered: true,
      _mock: true,
      _message: "MOCK: Simulated ASR transcription from Indic-ASR pipeline."
    };
  }

  /**
   * Mock Agent Handle: Natural Language Parsing & Slot Filling
   */
  async function agentHandle(text, session = "sess-default") {
    await delay(500);

    const clean = (text || "").toLowerCase();

    // Extract numerical values
    const numbers = (text.match(/\d+/g) || []).map(Number);
    let income = 0;
    let expense = 0;
    let owner = 0;
    let category = "petrol";

    if (numbers.length >= 3) {
      income = numbers[0];
      expense = numbers[1];
      owner = numbers[2];
    } else if (numbers.length === 2) {
      income = numbers[0];
      expense = numbers[1];
    } else if (numbers.length === 1) {
      if (/collection|fare|earning|வசூல்/i.test(clean)) {
        income = numbers[0];
      } else if (/petrol|diesel|gas|fuel|expense|செலவு/i.test(clean)) {
        expense = numbers[0];
      } else if (/owner|bhatta|வாடகை/i.test(clean)) {
        owner = numbers[0];
      } else {
        income = numbers[0];
      }
    } else {
      // Default fallback sample numbers if none spoken
      income = 1500;
      expense = 300;
      owner = 200;
    }

    if (/diesel|டீசல்/i.test(clean)) category = "diesel";
    else if (/tea|food|சாப்பாடு|டிபன்/i.test(clean)) category = "food";
    else if (/puncture|tyre|service|பழுது/i.test(clean)) category = "maintenance";
    else if (/toll|பார்க்கிங்/i.test(clean)) category = "toll";

    const net = income - expense - owner;
    const pendingId = "mock-tx-" + Date.now();

    const replyText = `Vanakkam! Understood: Collection ₹${income}, ${category} ₹${expense}, Owner payout ₹${owner}. Net take-home ₹${net}. Shall I save this?`;

    return {
      intent: "log_transaction",
      confidence: 0.94,
      entities: {
        income: income,
        expense: expense,
        category: category,
        owner_payment: owner,
        net_balance: net
      },
      needs_confirm: true,
      reply_text: replyText,
      pending_id: pendingId,
      trace_steps: [
        { step: 1, title: "Acoustic Noise Gate", detail: "Filtered 120Hz-400Hz engine hum. SNR 24.2 dB.", status: "complete" },
        { step: 2, title: "Speech Recognition", detail: `Transcribed: "${text || 'Audio input'}"`, status: "complete" },
        { step: 3, title: "Language Classification", detail: "Detected Tanglish / Tamil blend (Indic-ASR)", status: "complete" },
        { step: 4, title: "NLU Intent Parsing", detail: "Classified Intent: log_transaction (Score: 0.96)", status: "complete" },
        { step: 5, title: "Slot Filling & Entity Extraction", detail: `income=₹${income}, expense=₹${expense} (${category}), owner=₹${owner}`, status: "complete" },
        { step: 6, title: "Driver Confirmation Gate", detail: "Waiting for driver tactile confirmation.", status: "waiting" }
      ],
      _mock: true,
      _message: "MOCK: Result extracted locally. No live LLM was invoked."
    };
  }

  /**
   * Mock Confirm: Save or Cancel
   */
  async function confirm(pendingId, decision) {
    await delay(400);

    if (decision) {
      return {
        saved_status: "confirmed",
        result: "MOCK: Transaction approved! Added to in-memory session ledger.",
        persisted_to_db: false,
        _mock: true,
        _message: "MOCK MODE: Data retained in browser memory only. No database write."
      };
    } else {
      return {
        saved_status: "cancelled",
        result: "MOCK: Transaction cancelled by driver. No changes made.",
        persisted_to_db: false,
        _mock: true
      };
    }
  }

  /**
   * Mock Finance Summary
   */
  async function getSummary(period = "today") {
    await delay(350);
    return {
      ...mockDB.finance,
      active_period: period,
      _mock: true
    };
  }

  /**
   * Mock Documents List
   */
  async function documentsList() {
    await delay(300);
    return {
      documents: mockDB.documents,
      _mock: true
    };
  }

  /**
   * Mock Document Add
   */
  async function documentAdd(data) {
    await delay(400);

    const expiryDate = new Date(data.expiry);
    const today = new Date();
    const daysLeft = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));
    let status = "safe";
    if (daysLeft < 7) status = "danger";
    else if (daysLeft < 30) status = "warning";

    const newDoc = {
      id: "doc-" + Date.now(),
      type: data.type || "Other Document",
      number: data.number || "TN-MOCK-000",
      expiry: data.expiry,
      days_left: daysLeft,
      status: status
    };

    mockDB.documents.push(newDoc);

    return {
      saved: true,
      document: newDoc,
      _mock: true,
      _message: "MOCK: Document stored in browser memory only."
    };
  }

  /**
   * Mock Settlement Comparison
   */
  async function settlementCompare(driverAmount, ownerExpected) {
    await delay(350);

    const dAmt = Number(driverAmount) || 0;
    const oExp = Number(ownerExpected) || 0;
    const diff = dAmt - oExp;

    let status = "MATCHED";
    if (diff > 0) status = "DRIVER_SURPLUS";
    else if (diff < 0) status = "DUE_TO_OWNER";

    return {
      driver_collection: dAmt,
      owner_expected: oExp,
      difference: diff,
      settlement_status: status,
      _mock: true
    };
  }

  /**
   * Mock Speak (TTS)
   */
  async function speak(text, lang = "ta") {
    await delay(300);
    return {
      available: false,
      text_rendered: text,
      message: "MOCK: Gnani Timbre TTS voice synthesis simulated. Web Speech API fallback available.",
      _mock: true
    };
  }

  // Export to global namespace
  window.MockAPI = {
    transcribe,
    agentHandle,
    confirm,
    getSummary,
    documentsList,
    documentAdd,
    settlementCompare,
    speak,
    mockDB
  };

})();

