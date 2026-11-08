/**
 * T2T DRIVE — VEHICLE HEALTH & MAINTENANCE MODULE
 * Auto telemetry, preventative service countdowns, and maintenance expenditure logs.
 */

(function () {
  'use strict';

  // DOM Elements
  const serviceTimeline = document.getElementById("serviceTimeline");
  const addMaintenanceForm = document.getElementById("addMaintenanceForm");
  const maintServiceType = document.getElementById("maintServiceType");
  const maintDate = document.getElementById("maintDate");
  const maintCost = document.getElementById("maintCost");
  const maintWorkshop = document.getElementById("maintWorkshop");
  const maintenanceHistoryTableBody = document.getElementById("maintenanceHistoryTableBody");

  // In-Memory Vehicle State
  let vehicleState = {
    odometer: 64280,
    schedule: [
      { id: "srv-1", title: "Engine Oil & Filter Change", intervalKm: 5000, lastKm: 60000, dueKm: 65000, dueInKm: 720, urgency: "warning" },
      { id: "srv-2", title: "Brake Liner & Drum Check", intervalKm: 10000, lastKm: 57000, dueKm: 67000, dueInKm: 2720, urgency: "safe" },
      { id: "srv-3", title: "Spark Plug & Carburetor Tune", intervalKm: 8000, lastKm: 58000, dueKm: 66000, dueInKm: 1720, urgency: "safe" },
      { id: "srv-4", title: "Clutch Wire & Accelerator Cable", intervalKm: 6000, lastKm: 58500, dueKm: 64500, dueInKm: 220, urgency: "danger" }
    ],
    history: [
      { date: "22 Oct 2026", type: "Engine Oil & Filter Change", garage: "Shanmugam Auto Works, T.Nagar", odo: "63,800 km", cost: 450 },
      { date: "10 Sep 2026", type: "Brake Shoe Replacement", garage: "Ramesh Auto Care, Vadapalani", odo: "62,100 km", cost: 380 },
      { date: "15 Jul 2026", type: "Tyre Replacement / Tube", garage: "MRF Tyres, Kodambakkam", odo: "59,400 km", cost: 1250 }
    ]
  };

  function formatINR(val) {
    return "₹" + Number(val || 0).toLocaleString("en-IN");
  }

  /**
   * Render Service Milestones Timeline
   */
  function renderServiceTimeline() {
    if (!serviceTimeline) return;
    serviceTimeline.innerHTML = "";

    vehicleState.schedule.forEach(item => {
      const step = document.createElement("div");
      step.className = "service-step-item";

      let badgeClass = "safe";
      let badgeLabel = "SCHEDULED";
      let borderAccent = "var(--success)";

      if (item.dueInKm <= 300) {
        badgeClass = "danger";
        badgeLabel = "URGENT SERVICE";
        borderAccent = "var(--danger)";
      } else if (item.dueInKm <= 1000) {
        badgeClass = "warning";
        badgeLabel = "DUE SOON";
        borderAccent = "var(--warning)";
      }

      step.style.borderLeftColor = borderAccent;

      step.innerHTML = `
        <div>
          <h4 style="font-size:14px;font-weight:700;color:var(--text-main);">${item.title}</h4>
          <span class="input-hint">Due at <strong>${item.dueKm.toLocaleString("en-IN")} km</strong> (Odometer: ${vehicleState.odometer.toLocaleString("en-IN")} km)</span>
        </div>
        <div style="text-align:right;">
          <span class="doc-status-badge ${badgeClass}" style="display:inline-block;margin-bottom:4px;">${badgeLabel}</span>
          <div style="font-size:12px;font-family:var(--font-mono);font-weight:700;color:var(--text-main);">
            In ${item.dueInKm.toLocaleString("en-IN")} km
          </div>
        </div>
      `;
      serviceTimeline.appendChild(step);
    });
  }

  /**
   * Render Maintenance History Table
   */
  function renderMaintenanceHistory() {
    if (!maintenanceHistoryTableBody) return;
    maintenanceHistoryTableBody.innerHTML = "";

    vehicleState.history.forEach(log => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${log.date}</strong></td>
        <td><span class="pill pill-live">${log.type}</span></td>
        <td>${log.garage}</td>
        <td><span class="font-mono">${log.odo}</span></td>
        <td class="text-right"><strong class="text-danger">${formatINR(log.cost)}</strong></td>
      `;
      maintenanceHistoryTableBody.appendChild(tr);
    });
  }

  /**
   * Handle Maintenance Form Submission
   */
  function handleAddMaintenance(e) {
    e.preventDefault();

    const type = maintServiceType.value;
    const date = maintDate.value;
    const cost = Number(maintCost.value) || 0;
    const workshop = maintWorkshop.value.trim() || "Local Garage";

    if (!type || !date) {
      if (window.showToast) window.showToast("Please select service type and date.", "warning");
      return;
    }

    const newLog = {
      date: formatDate(date),
      type: type,
      garage: workshop,
      odo: `${vehicleState.odometer.toLocaleString("en-IN")} km`,
      cost: cost
    };

    vehicleState.history.unshift(newLog);
    renderMaintenanceHistory();

    // Cross-module update: deduct from finance expenses
    if (window.FinanceModule && cost > 0) {
      window.FinanceModule.addTransaction({
        type: "expense",
        description: `Maintenance: ${type}`,
        amount: cost,
        mode: "Cash"
      });
    }

    if (window.showToast) {
      window.showToast(`Maintenance logged: ${type} (${formatINR(cost)})`, "success");
    }

    addMaintenanceForm.reset();
    setTodayDate();
  }

  function formatDate(dStr) {
    try {
      const d = new Date(dStr);
      return d.toLocaleDateString("en-IN", { day: '2-digit', month: 'short', year: 'numeric' });
    } catch (e) {
      return dStr;
    }
  }

  function setTodayDate() {
    if (maintDate) {
      const today = new Date().toISOString().split("T")[0];
      maintDate.value = today;
    }
  }

  /**
   * Initialize Module Listeners
   */
  function initVehicleModule() {
    if (addMaintenanceForm) {
      addMaintenanceForm.addEventListener("submit", handleAddMaintenance);
    }

    setTodayDate();
    renderServiceTimeline();
    renderMaintenanceHistory();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initVehicleModule);
  } else {
    initVehicleModule();
  }

  // Export
  window.VehicleModule = {
    renderServiceTimeline,
    renderMaintenanceHistory
  };

})();

