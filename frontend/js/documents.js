/**
 * T2T DRIVE — DOCUMENTS VAULT MODULE
 * Driver and vehicle document tracker, days-to-expire countdowns,
 * RTO compliance warning badges, and modal registration.
 */

(function () {
  'use strict';

  // DOM Elements
  const documentsCardsGrid = document.getElementById("documentsCardsGrid");
  const complianceText = document.getElementById("complianceText");
  const openAddDocModalBtn = document.getElementById("openAddDocModalBtn");
  const addDocModal = document.getElementById("addDocModal");
  const closeDocModalBtn = document.getElementById("closeDocModalBtn");
  const cancelDocModalBtn = document.getElementById("cancelDocModalBtn");
  const addDocumentForm = document.getElementById("addDocumentForm");
  const docTypeSelect = document.getElementById("docTypeSelect");
  const docNumberInput = document.getElementById("docNumberInput");
  const docExpiryInput = document.getElementById("docExpiryInput");
  const docExpBadge = document.getElementById("docExpBadge");

  // In-Memory Documents List
  let documentsState = [
    { id: "doc-1", type: "Driving Licence (DL)", number: "TN-09-2018-004821", expiry: "2028-10-14", days_left: 705, status: "safe", icon: "🪪" },
    { id: "doc-2", type: "Vehicle Insurance", number: "POL-ICICI-884219", expiry: "2026-11-28", days_left: 20, status: "warning", icon: "🛡️" },
    { id: "doc-3", type: "Auto Permit", number: "PRM-CHENNAI-3921", expiry: "2027-04-10", days_left: 153, status: "safe", icon: "📜" },
    { id: "doc-4", type: "Fitness Certificate (FC)", number: "FC-RTO09-91823", expiry: "2026-11-14", days_left: 6, status: "danger", icon: "⚙️" },
    { id: "doc-5", type: "PUC (Pollution)", number: "PUC-EMISS-7721", expiry: "2027-01-15", days_left: 68, status: "safe", icon: "🌿" }
  ];

  /**
   * Calculate days remaining until expiry
   */
  function calculateDaysLeft(expiryDateStr) {
    const expiry = new Date(expiryDateStr);
    const today = new Date();
    // Normalize to midnight
    expiry.setHours(0, 0, 0, 0);
    today.setHours(0, 0, 0, 0);

    const diffMs = expiry.getTime() - today.getTime();
    return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  }

  /**
   * Map document type to a suitable icon
   */
  function getDocIcon(type) {
    if (/licence|dl/i.test(type)) return "🪪";
    if (/insurance/i.test(type)) return "🛡️";
    if (/permit/i.test(type)) return "📜";
    if (/fitness|fc/i.test(type)) return "⚙️";
    if (/puc|pollution/i.test(type)) return "🌿";
    return "📑";
  }

  /**
   * Render Document Cards Grid
   */
  function renderDocuments() {
    if (!documentsCardsGrid) return;
    documentsCardsGrid.innerHTML = "";

    let dangerCount = 0;
    let warningCount = 0;

    documentsState.forEach(doc => {
      const days = calculateDaysLeft(doc.expiry);
      doc.days_left = days;

      let status = "safe";
      let statusLabel = "VALID";
      let statusClass = "safe";

      if (days < 0) {
        status = "danger";
        statusLabel = "EXPIRED";
        statusClass = "danger";
        dangerCount++;
      } else if (days <= 7) {
        status = "danger";
        statusLabel = "CRITICAL";
        statusClass = "danger";
        dangerCount++;
      } else if (days <= 30) {
        status = "warning";
        statusLabel = "RENEW SOON";
        statusClass = "warning";
        warningCount++;
      }

      const card = document.createElement("div");
      card.className = "doc-card";
      card.innerHTML = `
        <div>
          <div class="doc-card-top">
            <div class="doc-type-badge">
              <div class="doc-icon-wrap">${getDocIcon(doc.type)}</div>
              <div>
                <h4 class="doc-name">${escapeHtml(doc.type)}</h4>
                <span class="doc-number">${escapeHtml(doc.number)}</span>
              </div>
            </div>
            <span class="doc-status-badge ${statusClass}">${statusLabel}</span>
          </div>

          <div class="field-group" style="margin-top:10px;">
            <span class="input-hint">Expires on:</span>
            <strong style="font-size:13px;color:var(--text-main);">${formatDate(doc.expiry)}</strong>
          </div>
        </div>

        <div class="doc-expiry-info">
          <span class="input-hint">Days Remaining:</span>
          <span class="days-left-count ${statusClass}">
            ${days < 0 ? `Expired ${Math.abs(days)}d ago` : `${days} Days Left`}
          </span>
        </div>
      `;
      documentsCardsGrid.appendChild(card);
    });

    // Update Compliance Summary
    const totalAlerts = dangerCount + warningCount;
    if (complianceText) {
      if (totalAlerts > 0) {
        complianceText.textContent = `${documentsState.length} documents monitored. ${dangerCount} critical and ${warningCount} expiring within 30 days!`;
      } else {
        complianceText.textContent = `All ${documentsState.length} documents are active and in full compliance.`;
      }
    }

    // Update Sidebar Navigation Badge
    if (docExpBadge) {
      if (totalAlerts > 0) {
        docExpBadge.textContent = `${totalAlerts} Alert`;
        docExpBadge.className = "nav-badge warning";
        docExpBadge.style.display = "inline-block";
      } else {
        docExpBadge.textContent = "All Good";
        docExpBadge.className = "nav-badge";
      }
    }
  }

  function formatDate(dateStr) {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-IN", { day: '2-digit', month: 'short', year: 'numeric' });
    } catch (e) {
      return dateStr;
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Modal Open / Close
   */
  function openModal() {
    if (addDocModal) {
      addDocModal.classList.add("open");
      if (docNumberInput) docNumberInput.focus();
    }
  }

  function closeModal() {
    if (addDocModal) {
      addDocModal.classList.remove("open");
      if (addDocumentForm) addDocumentForm.reset();
    }
  }

  /**
   * Handle Form Submission
   */
  async function handleAddDocumentSubmit(e) {
    e.preventDefault();

    const type = docTypeSelect.value;
    const number = docNumberInput.value.trim();
    const expiry = docExpiryInput.value;

    if (!type || !number || !expiry) {
      if (window.showToast) window.showToast("Please fill all required document fields.", "warning");
      return;
    }

    try {
      const res = await window.API.documentAdd({ type, number, expiry });

      if (res && res.saved) {
        documentsState.push({
          id: "doc-" + Date.now(),
          type,
          number,
          expiry,
          days_left: calculateDaysLeft(expiry),
          status: "safe",
          icon: getDocIcon(type)
        });

        renderDocuments();
        closeModal();

        if (window.showToast) {
          window.showToast(`Document "${type}" registered successfully!`, "success");
        }
      }
    } catch (err) {
      console.error("Add document error:", err);
      if (window.showToast) window.showToast("Failed to register document: " + err.message, "danger");
    }
  }

  /**
   * Fetch from backend or mock
   */
  async function loadDocuments() {
    try {
      const res = await window.API.documentsList();
      if (res && res.documents && res.documents.length > 0) {
        documentsState = res.documents.map(d => ({
          ...d,
          icon: getDocIcon(d.type)
        }));
      }
    } catch (err) {
      console.warn("Using local cache for documents:", err);
    }
    renderDocuments();
  }

  /**
   * Initialize Listeners
   */
  function initDocumentsModule() {
    if (openAddDocModalBtn) openAddDocModalBtn.addEventListener("click", openModal);
    if (closeDocModalBtn) closeDocModalBtn.addEventListener("click", closeModal);
    if (cancelDocModalBtn) cancelDocModalBtn.addEventListener("click", closeModal);

    if (addDocModal) {
      addDocModal.addEventListener("click", (e) => {
        if (e.target === addDocModal) closeModal();
      });
    }

    if (addDocumentForm) {
      addDocumentForm.addEventListener("submit", handleAddDocumentSubmit);
    }

    loadDocuments();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDocumentsModule);
  } else {
    initDocumentsModule();
  }

  // Export
  window.DocumentsModule = {
    loadDocuments,
    renderDocuments
  };

})();

