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
      transcribe:        "/api/speech/transcribe",
      agentMessage:      "/api/agent/message",
      agentConfirm:      "/api/agent/confirm",
      financeSummary:    "/api/finance/summary",
      documents:         "/api/documents",
      settlementCompare: "/api/settlement/compare",
      speak:             "/api/speech/speak"
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
    settlementCompare,
    speak
  };

})();
