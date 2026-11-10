/**
 * T2T DRIVE — API CLIENT SERVICE
 * Unified Fetch API client for Flask backend with instant fallback to MockAPI.
 * Configurable base URL, zero hardcoded secrets.
 */

(function () {
  'use strict';

  // Dynamically resolve API base: same-origin relative URLs by default, configurable via window.__T2T_API_BASE__
  function resolveApiBase() {
    if (typeof window !== "undefined" && window.__T2T_API_BASE__ !== undefined) {
      return window.__T2T_API_BASE__;
    }
    // Same-origin relative URLs for Render, production, and unified Flask hosting
    return "";
  }

  // Dynamically resolve mode: defaults to "live" for production real Gnani AI voice; supports window.__T2T_MODE__ or localStorage
  function resolveApiMode() {
    if (typeof window !== "undefined" && window.__T2T_MODE__ !== undefined) {
      return window.__T2T_MODE__;
    }
    try {
      const saved = (typeof localStorage !== "undefined") && localStorage.getItem("t2t_mode");
      if (saved === "mock" || saved === "live") {
        return saved;
      }
    } catch (e) {}
    // Production default is REAL LIVE Gnani AI voice and backend API integration
    return "live";
  }

  // Central Configuration
  window.T2T_CONFIG = {
    MODE: resolveApiMode(),            // "live" (production default) | "mock" (offline test toggle)
    API_BASE: resolveApiBase(),        // Same-origin relative API URL (empty prefix, no hardcoded localhost)
    TIMEOUT_MS: 12000,
    ENDPOINTS: {
      transcribe:          "/api/speech/transcribe",
      agentMessage:        "/api/agent/message",
      agentConfirm:        "/api/agent/confirm",
      financeSummary:      "/api/finance/summary",
      documents:           "/api/documents",
      documentCompliance:  "/api/documents/compliance",
      documentOCR:         "/api/documents/ocr-preview",
      challans:            "/api/challans",
      challanOCR:          "/api/challans/ocr-preview",
      maintenance:         "/api/maintenance",
      maintenanceUpcoming: "/api/maintenance/upcoming",
      maintenanceSpending: "/api/maintenance/spending-summary",
      reminders:           "/api/reminders",
      remindersScan:       "/api/reminders/scan",
      settlementCompare:   "/api/settlement/compare",
      speak:               "/api/speech/speak",
      analyzeAudio:        "/api/voice/analyze-audio",
      voiceChat:           "/api/voice/chat"
    }
  };

  /**
   * Token Storage and Session Management
   */
  function getAuthToken() {
    try {
      return localStorage.getItem("t2t_token") || sessionStorage.getItem("t2t_token") || "";
    } catch (e) {
      return "";
    }
  }

  function setAuthToken(token) {
    if (!token) return;
    try {
      localStorage.setItem("t2t_token", token);
    } catch (e) {}
  }

  let _tokenPromise = null;
  async function ensureAuthToken() {
    let token = getAuthToken();
    if (token) return token;

    if (_tokenPromise) return await _tokenPromise;

    _tokenPromise = (async () => {
      try {
        const url = (window.T2T_CONFIG.API_BASE || "") + "/api/auth/demo-session";
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });
        if (res.ok) {
          const json = await res.json();
          const data = json && json.data ? json.data : json;
          if (data && data.token) {
            setAuthToken(data.token);
            return data.token;
          }
        }
      } catch (err) {
        console.warn("[T2T] Auto session authentication attempt:", err);
      } finally {
        _tokenPromise = null;
      }
      return getAuthToken();
    })();

    return await _tokenPromise;
  }

  /**
   * Helper to retrieve auth headers with Bearer token
   */
  function getAuthHeaders(customHeaders = {}) {
    const token = getAuthToken();
    const headers = { ...customHeaders };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
  }

  /**
   * Helper for robust JSON HTTP requests with timeout and 401 retry
   */
  async function fetchWithTimeout(url, options = {}, retryCount = 0) {
    if (!getAuthToken() && !url.includes("/api/auth/demo-session") && !url.includes("/api/auth/request-otp") && !url.includes("/api/auth/verify-otp")) {
      await ensureAuthToken();
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), window.T2T_CONFIG.TIMEOUT_MS);

    try {
      const mergedHeaders = getAuthHeaders(options.headers || {});
      let response = await fetch(url, {
        ...options,
        headers: mergedHeaders,
        signal: controller.signal
      });

      // If token expired or unauthorized, refresh session and retry at most once (infinite loop guard)
      if (response.status === 401 && retryCount < 1 && !url.includes("/api/auth/")) {
        clearTimeout(timer);
        try { localStorage.removeItem("t2t_token"); } catch (e) {}
        const freshToken = await ensureAuthToken();
        if (freshToken) {
          return await fetchWithTimeout(url, options, retryCount + 1);
        }
      }

      clearTimeout(timer);

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        let msg = errorText;
        try {
          const j = JSON.parse(errorText);
          if (j && j.error && j.error.message) msg = j.error.message;
        } catch (e) {}
        throw new Error(`HTTP ${response.status}: ${msg || response.statusText}`);
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

    if (!getAuthToken()) {
      await ensureAuthToken();
    }

    const formData = new FormData();
    if (audio) {
      const audioName = (audio && audio.name) ? audio.name : "audio-input.wav";
      formData.append("audio", audio, audioName);
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
   * POST /api/voice/chat
   * Unified end-to-end voice co-pilot workflow:
   * Audio Upload -> Prisma STT -> LangGraph Agent -> Confirmation Firewall -> Timbre TTS
   * @param {Blob|File} audio
   * @param {string} lang ("tanglish" | "ta-IN" | "en-IN" | "indic-auto")
   * @param {string|null} sessionId
   * @param {boolean} generateTts
   */
  async function voiceChat(audio, lang = "tanglish", sessionId = null, generateTts = true) {
    if (window.T2T_CONFIG.MODE === "mock") {
      return await window.MockAPI.voiceChat(audio, lang, sessionId, generateTts);
    }

    if (!getAuthToken()) {
      await ensureAuthToken();
    }

    const formData = new FormData();
    if (audio) {
      const audioName = (audio && audio.name) ? audio.name : "audio-input.wav";
      formData.append("audio", audio, audioName);
    }
    formData.append("lang", lang);
    if (sessionId) {
      formData.append("session_id", sessionId);
    }
    formData.append("generate_tts", generateTts ? "true" : "false");

    const url = window.T2T_CONFIG.API_BASE + (window.T2T_CONFIG.ENDPOINTS.voiceChat || "/api/voice/chat");
    const reqHeaders = getAuthHeaders(); // Does NOT set Content-Type so multipart boundary is auto-generated
    const res = await fetch(url, {
      method: "POST",
      headers: reqHeaders,
      body: formData
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let parsedErr = text;
      try {
        const jsonErr = JSON.parse(text);
        if (jsonErr && jsonErr.error && jsonErr.error.message) {
          parsedErr = jsonErr.error.message;
        }
      } catch (e) {}
      throw new Error(`Voice turn failed (${res.status}): ${parsedErr}`);
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
   * POST /api/documents/ocr-preview
   */
  async function documentPreviewOCR(file) {
    const url = window.T2T_CONFIG.API_BASE + window.T2T_CONFIG.ENDPOINTS.documentOCR;
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
      throw new Error(`Document OCR preview failed (${res.status}): ${text}`);
    }
    const json = await res.json();
    return (json && json.data !== undefined) ? json.data : json;
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

  /**
   * POST /api/voice/analyze-audio (Phase 6 Noise Intelligence)
   * @param {Blob} audioBlob
   * @param {string} lang
   */
  async function analyzeAudio(audioBlob, lang = "tanglish") {
    const url = window.T2T_CONFIG.API_BASE + (window.T2T_CONFIG.ENDPOINTS.analyzeAudio || "/api/voice/analyze-audio");
    const formData = new FormData();
    formData.append("file", audioBlob, "recording.wav");
    formData.append("language", lang);

    return await fetchWithTimeout(url, {
      method: "POST",
      body: formData
    });
  }

  // Export to global API object
  window.API = {
    transcribe,
    voiceChat,
    analyzeAudio,
    agentHandle,
    confirm,
    getSummary,
    documentsList,
    documentAdd,
    documentCompliance,
    documentPreviewOCR,
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
    speak,
    ensureAuthToken,
    getAuthToken,
    setAuthToken
  };

})();
