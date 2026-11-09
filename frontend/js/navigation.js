/**
 * T2T DRIVE — NAVIGATION & UI ROUTING CONTROLLER
 * Handles responsive sidebar, hash-routing, keyboard shortcuts, and command palette.
 */

(function () {
  'use strict';

  // Section titles and taglines mapping
  const viewMeta = {
    copilot: {
      title: "Voice Co-Pilot",
      tagline: "Speak Naturally. Manage Intelligently. Drive Smarter."
    },
    trips: {
      title: "Trips & Passenger Agreement",
      tagline: "Live Trip QR, Mutual Agreement, Continuous Listening & Fair Fare Reconciliation"
    },
    finance: {
      title: "Finance Dashboard",
      tagline: "Track Collections, Fuel Costs, and Daily Net Earnings"
    },
    documents: {
      title: "Driver & Vehicle Documents",
      tagline: "RTO Compliance, Expiry Warnings & Renewal Reminders"
    },
    settlement: {
      title: "Owner-Driver Daily Settlement",
      tagline: "Transparent Bhatta, Collections & Dues Reconciliation"
    },
    vehicle: {
      title: "Vehicle Health & Maintenance",
      tagline: "Auto Telemetry, Service Logs & Preventive Care"
    },
    agent: {
      title: "Agent & AI Diagnostic Console",
      tagline: "Gnani ASR Telemetry, Intent Classifier, Slot-Filling & SNR Evaluation"
    }
  };

  // DOM Elements
  const mobileMenuBtn = document.getElementById("mobileMenuBtn");
  const appSidebar = document.getElementById("appSidebar");
  const sidebarOverlay = document.getElementById("sidebarOverlay");
  const topbarViewTitle = document.getElementById("topbarViewTitle");
  const topbarTagline = document.getElementById("topbarTagline");
  const navItems = document.querySelectorAll(".nav-item");
  const dashboardViews = document.querySelectorAll(".dashboard-view");
  const fabVoiceBtn = document.getElementById("fabVoiceBtn");
  const langPills = document.querySelectorAll(".lang-pill");
  const searchPaletteBtn = document.getElementById("searchPaletteBtn");
  const paletteBackdrop = document.getElementById("paletteBackdrop");
  const paletteSearchInput = document.getElementById("paletteSearchInput");
  const paletteResults = document.getElementById("paletteResults");

  // Current active language (default: tanglish)
  window.currentLanguage = "tanglish";

  /**
   * Switch the active view based on hash or view name
   */
  function navigateTo(viewName) {
    if (!viewMeta[viewName]) {
      viewName = "copilot";
    }

    // Update URL hash without extra history spam
    if (window.location.hash !== `#${viewName}`) {
      window.location.hash = `#${viewName}`;
    }

    // Update Topbar
    if (topbarViewTitle) topbarViewTitle.textContent = viewMeta[viewName].title;
    if (topbarTagline) topbarTagline.textContent = viewMeta[viewName].tagline;

    // Toggle active class on views
    dashboardViews.forEach(view => {
      const isTarget = view.id === `view-${viewName}`;
      view.classList.toggle("active", isTarget);
      if (isTarget) {
        // Broadcast custom view-entered event
        window.dispatchEvent(new CustomEvent("viewChanged", { detail: { view: viewName } }));
      }
    });

    // Update active nav-item
    navItems.forEach(item => {
      const target = item.getAttribute("data-view");
      item.classList.toggle("active", target === viewName);
    });

    // Close mobile drawer if open
    closeMobileSidebar();

    // Scroll to top of viewport
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /**
   * Mobile Sidebar Drawer Controls
   */
  function toggleMobileSidebar() {
    const isOpen = appSidebar.classList.toggle("open");
    sidebarOverlay.classList.toggle("active", isOpen);
    mobileMenuBtn.classList.toggle("open", isOpen);
  }

  function closeMobileSidebar() {
    appSidebar.classList.remove("open");
    sidebarOverlay.classList.remove("active");
    mobileMenuBtn.classList.remove("open");
  }

  /**
   * Setup Language Selector Pills
   */
  function setupLanguagePills() {
    langPills.forEach(pill => {
      pill.addEventListener("click", () => {
        langPills.forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        window.currentLanguage = pill.getAttribute("data-lang");
        
        if (window.showToast) {
          window.showToast(`Speech Language set to: ${pill.textContent}`, "info");
        }
      });
    });
  }

  /**
   * Command Palette Commands & Search
   */
  const paletteCommands = [
    { label: "Go to Voice Co-Pilot", icon: "🎙️", action: () => navigateTo("copilot"), shortcut: "Alt+1" },
    { label: "Go to Finance Dashboard", icon: "💰", action: () => navigateTo("finance"), shortcut: "Alt+2" },
    { label: "Go to Documents Vault", icon: "📑", action: () => navigateTo("documents"), shortcut: "Alt+3" },
    { label: "Go to Owner Settlement", icon: "🤝", action: () => navigateTo("settlement"), shortcut: "Alt+4" },
    { label: "Go to Vehicle Health", icon: "🛺", action: () => navigateTo("vehicle"), shortcut: "Alt+5" },
    { label: "Go to Agent & AI Trace", icon: "🧠", action: () => navigateTo("agent"), shortcut: "Alt+6" },
    { label: "Toggle Dark / Light Mode", icon: "☀️", action: () => window.toggleTheme && window.toggleTheme() },
    { label: "Toggle Live / Mock API Mode", icon: "⚡", action: () => window.toggleSystemMode && window.toggleSystemMode() },
    { label: "Trigger Quick Voice Prompt", icon: "🎤", action: () => {
      navigateTo("copilot");
      setTimeout(() => {
        const ptt = document.getElementById("pttBtn");
        if (ptt) ptt.click();
      }, 200);
    }}
  ];

  function openPalette() {
    if (!paletteBackdrop) return;
    paletteBackdrop.classList.add("open");
    paletteSearchInput.value = "";
    renderPaletteResults(paletteCommands);
    setTimeout(() => paletteSearchInput.focus(), 50);
  }

  function closePalette() {
    if (!paletteBackdrop) return;
    paletteBackdrop.classList.remove("open");
  }

  function renderPaletteResults(commands) {
    if (!paletteResults) return;
    paletteResults.innerHTML = "";

    if (commands.length === 0) {
      paletteResults.innerHTML = `<div class="palette-item" style="justify-content:center;color:var(--text-subtle);">No matching actions found</div>`;
      return;
    }

    commands.forEach(cmd => {
      const el = document.createElement("div");
      el.className = "palette-item";
      el.innerHTML = `
        <span style="display:flex;align-items:center;gap:10px;">
          <span>${cmd.icon}</span>
          <strong>${cmd.label}</strong>
        </span>
        ${cmd.shortcut ? `<span class="kbd-pill" style="position:static">${cmd.shortcut}</span>` : ""}
      `;
      el.addEventListener("click", () => {
        closePalette();
        cmd.action();
      });
      paletteResults.appendChild(el);
    });
  }

  /**
   * Initialize Listeners
   */
  function initNavigation() {
    // Nav link click listeners
    navItems.forEach(link => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const targetView = link.getAttribute("data-view");
        navigateTo(targetView);
      });
    });

    // Mobile menu toggles
    if (mobileMenuBtn) mobileMenuBtn.addEventListener("click", toggleMobileSidebar);
    if (sidebarOverlay) sidebarOverlay.addEventListener("click", closeMobileSidebar);

    // Floating action button
    if (fabVoiceBtn) {
      fabVoiceBtn.addEventListener("click", () => {
        navigateTo("copilot");
        const ptt = document.getElementById("pttBtn");
        if (ptt) ptt.focus();
      });
    }

    // Command palette openers
    if (searchPaletteBtn) searchPaletteBtn.addEventListener("click", openPalette);
    if (paletteBackdrop) {
      paletteBackdrop.addEventListener("click", (e) => {
        if (e.target === paletteBackdrop) closePalette();
      });
    }

    // Search filter input
    if (paletteSearchInput) {
      paletteSearchInput.addEventListener("input", (e) => {
        const query = e.target.value.toLowerCase().trim();
        const filtered = paletteCommands.filter(c => c.label.toLowerCase().includes(query));
        renderPaletteResults(filtered);
      });
    }

    // Keyboard Shortcuts
    window.addEventListener("keydown", (e) => {
      // Cmd+K or Ctrl+K opens palette
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        paletteBackdrop && paletteBackdrop.classList.contains("open") ? closePalette() : openPalette();
        return;
      }

      // Escape closes palette or open modals
      if (e.key === "Escape") {
        closePalette();
        const addDocModal = document.getElementById("addDocModal");
        if (addDocModal) addDocModal.classList.remove("open");
      }

      // Alt + 1-6 quick jump
      if (e.altKey) {
        if (e.key === "1") { e.preventDefault(); navigateTo("copilot"); }
        if (e.key === "2") { e.preventDefault(); navigateTo("finance"); }
        if (e.key === "3") { e.preventDefault(); navigateTo("documents"); }
        if (e.key === "4") { e.preventDefault(); navigateTo("settlement"); }
        if (e.key === "5") { e.preventDefault(); navigateTo("vehicle"); }
        if (e.key === "6") { e.preventDefault(); navigateTo("agent"); }
      }
    });

    // Handle initial route on page load and hash changes
    window.addEventListener("hashchange", () => {
      const hash = window.location.hash.replace("#", "");
      if (hash && viewMeta[hash]) {
        navigateTo(hash);
      }
    });

    // Check initial hash
    const initialHash = window.location.hash.replace("#", "");
    navigateTo(initialHash || "copilot");

    setupLanguagePills();
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNavigation);
  } else {
    initNavigation();
  }

  // Export helper
  window.navigateTo = navigateTo;

})();

