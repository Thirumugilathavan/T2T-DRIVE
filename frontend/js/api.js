/**
 * T2T DRIVE — API CLIENT SERVICE
 * Unified Fetch API client for Flask backend with instant fallback to MockAPI.
 * Configurable base URL, zero hardcoded secrets.
 */

(function () {
  'use strict';

  // Central Configuration
  window.T2T_CONFIG = {
    MODE: "mock",                      // "mock" | "live"
    API_BASE: "http://localhost:5000", // Flask backend base URL
    TIMEOUT_MS: 12000,
    ENDPOINTS: {
      transcribe:          "/api/speech/transcribe",
      agentMessage:        "/api/agent/message",
      agentConfirm:        "/api/agent/confirm",
      financeSummary:      "/api/finance/summary",
      documents:           "/api/documents",
      documentCompliance:  "/api/documents/compliance",
      challans:            "/api/challans",
      challanOCR:          "/api/challans/ocr-preview",
      maintenance:         "/api/maintenance",
      maintenanceUpcoming: "/api/maintenance/upcoming",
      maintenanceSpending: "/api/maintenance/spending-summary",
      reminders:           "/api/reminders",
      remindersScan:       "/api/reminders/scan",
      settlementCompare:   "/api/settlement/compare",
      speak:               "/api/speech/speak"
    }
  };

  /**
   * Helper to retrieve auth headers if token exists
   */
  function getAuthHeaders(customHeaders = {}) {
    const token = localStorage.getItem("t2t_token") || sessionStorage.getItem("t2t_token");
    const headers = { ...customHeaders };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
  }

  /**
   * Helper for robust JSON HTTP requests with timeout
   */
  async function fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), window.T2T_CONFIG.TIMEOUT_MS);

    try {
      const mergedHeaders = getAuthHeaders(options.headers || {});
      const response = await fetch(url, {
        ...options,
        headers: mergedHeaders,
        signal: controller.signal
      });
      clearTimeout(timer);

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
      }
      const json = await response.json();
      return (json && json.data !== undefined) ? json.data : json;
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') {
        throw new Error("Request timed out. Please check backend connection.");
      }
      throw err;
    }
  }

  /**
   * POST /api/speech/transcribe
   * @param {Blob|File} audio
   * @param {string} lang ("tanglish" | "ta" | "en")
   */
  async function transcribe(audio, lang = "tanglish") {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.transcribe(audio, lang);
    }

    const formData = new FormData();
    if (audio) {
      formData.append("audio", audio, "audio-input.wav");
    }
    formData.append("lang", lang);

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.transcribe;
    const reqHeaders = getAuthHeaders();
    const res = await fetch(url, {
      method: "POST",
      headers: reqHeaders,
      body: formData
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Speech transcription failed (${res.status}): ${text}`);
    }
    const json = await res.json();
    return (json && json.data !== undefined) ? json.data : json;
  }

  /**
   * POST /api/agent/message
   * @param {string} text
   * @param {string} session
   */
  async function agentHandle(text, session = "sess-driver-1") {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.agentHandle(text, session);
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.agentMessage;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, session })
    });
  }

  /**
   * POST /api/agent/confirm
   * @param {string} pendingId
   * @param {boolean} decision
   */
  async function confirm(pendingId, decision) {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.confirm(pendingId, decision);
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.agentConfirm;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_id: pendingId, yes_or_no: !!decision })
    });
  }

  /**
   * GET /api/finance/summary?period=...
   * @param {string} period ("today" | "weekly" | "monthly")
   */
  async function getSummary(period = "today") {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.getSummary(period);
    }

    const url = `${window.T2T_CONFIG.API_BASE}${window.T2T_CONFIG.ENDPOINTS.financeSummary}?period=${encodeURIComponent(period)}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * GET /api/documents
   */
  async function documentsList() {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.documentsList();
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.documents;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * POST /api/documents
   * @param {Object} data { type, number, expiry }
   */
  async function documentAdd(data) {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.documentAdd(data);
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.documents;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
  }

  /**
   * GET /api/documents/compliance
   */
  async function documentCompliance(vehicleId) {
    let url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.documentCompliance;
    if (vehicleId) url += `?vehicle_id=${encodeURIComponent(vehicleId)}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * GET /api/challans
   */
  async function challansList(status, vehicleId) {
    let url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.challans;
    const params = [];
    if (status) params.push(`status=${encodeURIComponent(status)}`);
    if (vehicleId) params.push(`vehicle_id=${encodeURIComponent(vehicleId)}`);
    if (params.length) url += `?${params.join("&")}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * POST /api/challans
   */
  async function challanAdd(data) {
    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.challans;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
  }

  /**
   * POST /api/challans/:id/pay
   */
  async function challanPay(challanId, paymentData) {
    const url = `${window.T2T_CONFIG.API_BASE}${window.T2T_CONFIG.ENDPOINTS.challans}/${encodeURIComponent(challanId)}/pay`;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(paymentData || {})
    });
  }

  /**
   * POST /api/challans/ocr-preview
   */
  async function challanPreviewOCR(file) {
    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.challanOCR;
    const formData = new FormData();
    formData.append("file", file);
    const reqHeaders = getAuthHeaders();
    const res = await fetch(url, {
      method: "POST",
      headers: reqHeaders,
      body: formData
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`OCR preview failed (${res.status}): ${text}`);
    }
    const json = await res.json();
    return (json && json.data !== undefined) ? json.data : json;
  }

  /**
   * GET /api/maintenance
   */
  async function maintenanceList(vehicleId, limit = 50) {
    let url = `${window.T2T_CONFIG.API_BASE}${window.T2T_CONFIG.ENDPOINTS.maintenance}?limit=${limit}`;
    if (vehicleId) url += `&vehicle_id=${encodeURIComponent(vehicleId)}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * POST /api/maintenance
   */
  async function maintenanceAdd(data) {
    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.maintenance;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
  }

  /**
   * GET /api/maintenance/upcoming
   */
  async function maintenanceUpcoming(vehicleId) {
    let url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.maintenanceUpcoming;
    if (vehicleId) url += `?vehicle_id=${encodeURIComponent(vehicleId)}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * GET /api/maintenance/spending-summary
   */
  async function maintenanceSpendingSummary(startDate, endDate) {
    let url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.maintenanceSpending;
    const params = [];
    if (startDate) params.push(`start_date=${encodeURIComponent(startDate)}`);
    if (endDate) params.push(`end_date=${encodeURIComponent(endDate)}`);
    if (params.length) url += `?${params.join("&")}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * GET /api/reminders
   */
  async function remindersList(status) {
    let url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.reminders;
    if (status) url += `?status=${encodeURIComponent(status)}`;
    return await fetchWithTimeout(url, { method: "GET" });
  }

  /**
   * POST /api/reminders/scan
   */
  async function remindersScan(refDate) {
    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.remindersScan;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_date: refDate })
    });
  }

  /**
   * POST /api/reminders/:id/acknowledge
   */
  async function reminderAcknowledge(reminderId) {
    const url = `${window.T2T_CONFIG.API_BASE}${window.T2T_CONFIG.ENDPOINTS.reminders}/${encodeURIComponent(reminderId)}/acknowledge`;
    return await fetchWithTimeout(url, { method: "POST" });
  }

  /**
   * POST /api/settlement/compare
   * @param {Object} data { driver_amount, owner_amount }
   */
  async function settlementCompare(data) {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.settlementCompare(data.driver_amount, data.owner_amount);
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.settlementCompare;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
  }

  /**
   * POST /api/speech/speak
   * @param {string} text
   * @param {string} lang
   */
  async function speak(text, lang = "ta") {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.speak(text, lang);
    }

    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.speak;
    return await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang })
    });
  }

  // Export to global API object
  window.API = {
    transcribe,
    agentHandle,
    confirm,
    getSummary,
    documentsList,
    documentAdd,
    documentCompliance,
    challansList,
    challanAdd,
    challanPay,
    challanPreviewOCR,
    maintenanceList,
    maintenanceAdd,
    maintenanceUpcoming,
    maintenanceSpendingSummary,
    remindersList,
    remindersScan,
    reminderAcknowledge,
    settlementCompare,
    speak
  };

})();
