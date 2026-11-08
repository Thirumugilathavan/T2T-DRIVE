/**
 * T2T DRIVE — MASTER APPLICATION CONTROLLER
 * Initializes theme, system live/mock mode switching, global toasts, and error boundaries.
 */

(function () {
  'use strict';

  // DOM Elements
  const themeBtn = document.getElementById("themeBtn");
  const systemPulse = document.getElementById("systemPulse");
  const systemModeTitle = document.getElementById("systemModeTitle");
  const toggleModeBtn = document.getElementById("toggleModeBtn");
  const toastHub = document.getElementById("toastHub");

  /**
   * Theme Management (Dark by Default)
   */
  const THEME_STORAGE_KEY = "t2t-drive-theme";

  function initTheme() {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY) || "dark";
    document.documentElement.setAttribute("data-theme", savedTheme);

    if (themeBtn) {
      themeBtn.addEventListener("click", toggleTheme);
    }
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_STORAGE_KEY, next);

    showToast(`Switched to ${next.toUpperCase()} theme for optimal visibility.`, "info");
  }

  /**
   * System API Mode Toggle (MOCK <-> LIVE)
   */
  function initSystemMode() {
    updateModeUI();

    if (toggleModeBtn) {
      toggleModeBtn.addEventListener("click", toggleSystemMode);
    }
  }

  function toggleSystemMode() {
    const isMock = window.T2T_CONFIG.MODE === "mock";
    window.T2T_CONFIG.MODE = isMock ? "live" : "mock";

    updateModeUI();

    if (window.T2T_CONFIG.MODE === "live") {
      showToast(`Switched to LIVE API Mode. Targeting: ${window.T2T_CONFIG.API_BASE}`, "warning");
    } else {
      showToast("Switched to MOCK Offline Mode (Gnani AI Simulated).", "info");
    }
  }

  function updateModeUI() {
    const isLive = window.T2T_CONFIG.MODE === "live";

    if (systemPulse) {
      systemPulse.className = isLive ? "pulse-dot live" : "pulse-dot";
    }

    if (systemModeTitle) {
      systemModeTitle.textContent = isLive ? "LIVE API MODE" : "MOCK MODE";
      systemModeTitle.style.color = isLive ? "var(--success)" : "var(--primary)";
    }

    if (toggleModeBtn) {
      toggleModeBtn.textContent = isLive ? "Switch to Mock" : "Switch to Live";
    }
  }

  /**
   * Global Toast Notification System
   */
  function showToast(message, type = "info", duration = 3800) {
    if (!toastHub) return;

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    let icon = "ℹ️";
    if (type === "success") icon = "✓";
    else if (type === "danger") icon = "⚠️";
    else if (type === "warning") icon = "⚡";

    toast.innerHTML = `
      <span style="font-size:16px;">${icon}</span>
      <span>${message}</span>
    `;

    toastHub.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px)";
      toast.style.transition = "all 0.3s ease-out";
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  /**
   * Master Boot Routine
   */
  function bootApplication() {
    console.log("%c🛺 T2T DRIVE — AI Voice Co-Pilot Initialized", "color:#f59e0b;font-size:16px;font-weight:bold");
    console.log("%cSpeak Naturally. Manage Intelligently. Drive Smarter.", "color:#10b981;font-size:12px;");

    initTheme();
    initSystemMode();

    // Welcome Toast
    setTimeout(() => {
      showToast("Vanakkam! T2T DRIVE Voice Co-Pilot is ready.", "success");
    }, 800);
  }

  // Export Globals
  window.showToast = showToast;
  window.toggleTheme = toggleTheme;
  window.toggleSystemMode = toggleSystemMode;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootApplication);
  } else {
    bootApplication();
  }

})();

