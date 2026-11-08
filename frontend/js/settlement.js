/**
 * T2T DRIVE — OWNER-DRIVER SETTLEMENT MODULE
 * Daily reconciliation calculator, difference variance analysis,
 * and dispute-free settlement history ledger.
 */

(function () {
  'use strict';

  // DOM Elements
  const settlementCalcForm = document.getElementById("settlementCalcForm");
  const settleDriverCollection = document.getElementById("settleDriverCollection");
  const settleOwnerExpected = document.getElementById("settleOwnerExpected");
  const settleDriverFuel = document.getElementById("settleDriverFuel");
  const settleAmountPaid = document.getElementById("settleAmountPaid");
  const settlementResultBanner = document.getElementById("settlementResultBanner");
  const settleStatusPill = document.getElementById("settleStatusPill");
  const settleStatusTitle = document.getElementById("settleStatusTitle");
  const settleStatusDesc = document.getElementById("settleStatusDesc");
  const settleDiffAmount = document.getElementById("settleDiffAmount");
  const settlementHistoryTableBody = document.getElementById("settlementHistoryTableBody");

  // In-Memory Settlement State
  let settlementState = {
    driver_collection: 1500,
    owner_expected: 500,
    driver_fuel: 300,
    amount_paid: 500,
    history: [
      { date: "08 Nov 2026", collection: 1500, quota: 500, paid: 500, diff: 0, status: "MATCHED" },
      { date: "07 Nov 2026", collection: 1800, quota: 500, paid: 500, diff: 0, status: "MATCHED" },
      { date: "06 Nov 2026", collection: 1400, quota: 500, paid: 400, diff: -100, status: "DUE_TO_OWNER" },
      { date: "05 Nov 2026", collection: 1950, quota: 500, paid: 600, diff: 100, status: "DRIVER_SURPLUS" },
      { date: "04 Nov 2026", collection: 1600, quota: 500, paid: 500, diff: 0, status: "MATCHED" }
    ]
  };

  function formatINR(val) {
    return "₹" + Math.abs(Number(val) || 0).toLocaleString("en-IN");
  }

  /**
   * Calculate reconciliation and update banner
   */
  async function computeReconciliation() {
    const collection = Number(settleDriverCollection.value) || 0;
    const expected = Number(settleOwnerExpected.value) || 0;
    const paid = Number(settleAmountPaid.value) || 0;

    // Call API settlement compare
    try {
      const res = await window.API.settlementCompare({
        driver_amount: paid,
        owner_amount: expected
      });

      const diff = res.difference !== undefined ? res.difference : (paid - expected);
      let status = "MATCHED";

      if (diff > 0) status = "DRIVER_SURPLUS";
      else if (diff < 0) status = "DUE_TO_OWNER";

      renderSettlementResult(diff, status, collection, paid, expected);

    } catch (err) {
      console.warn("Settlement API compare fallback:", err);
      const diff = paid - expected;
      let status = diff === 0 ? "MATCHED" : diff > 0 ? "DRIVER_SURPLUS" : "DUE_TO_OWNER";
      renderSettlementResult(diff, status, collection, paid, expected);
    }
  }

  /**
   * Update Result UI Banner
   */
  function renderSettlementResult(diff, status, collection, paid, expected) {
    if (!settlementResultBanner) return;

    settlementResultBanner.className = "settlement-status-banner";

    if (status === "MATCHED" || diff === 0) {
      settlementResultBanner.classList.add("matched");
      settleStatusPill.textContent = "MATCHED";
      settleStatusTitle.textContent = "Settlement In Balance";
      settleStatusDesc.textContent = `Amount paid (₹${paid}) matches Owner target (₹${expected}). No dues on either side.`;
      settleDiffAmount.textContent = "₹0";
      settleDiffAmount.className = "diff-amount text-success";
    } else if (status === "DRIVER_SURPLUS" || diff > 0) {
      settlementResultBanner.classList.add("surplus");
      settleStatusPill.textContent = "DRIVER SURPLUS";
      settleStatusTitle.textContent = `Driver Advance: +${formatINR(diff)}`;
      settleStatusDesc.textContent = `Driver paid ₹${paid}, which is ₹${diff} more than agreed daily quota. To be adjusted tomorrow.`;
      settleDiffAmount.textContent = `+${formatINR(diff)}`;
      settleDiffAmount.className = "diff-amount text-warning";
    } else {
      settlementResultBanner.classList.add("due");
      settleStatusPill.textContent = "PENDING DUE";
      settleStatusTitle.textContent = `Pending Dues to Owner: -${formatINR(diff)}`;
      settleStatusDesc.textContent = `Driver paid ₹${paid}, leaving ₹${Math.abs(diff)} pending to reach owner daily target of ₹${expected}.`;
      settleDiffAmount.textContent = `-${formatINR(diff)}`;
      settleDiffAmount.className = "diff-amount text-danger";
    }
  }

  /**
   * Render Settlement History Ledger
   */
  function renderHistoryTable() {
    if (!settlementHistoryTableBody) return;
    settlementHistoryTableBody.innerHTML = "";

    settlementState.history.forEach(item => {
      const tr = document.createElement("tr");

      let statusPillClass = "pill-live";
      let diffColorClass = "text-success";
      let diffPrefix = "";

      if (item.diff > 0) {
        statusPillClass = "pill-beta";
        diffColorClass = "text-warning";
        diffPrefix = "+";
      } else if (item.diff < 0) {
        statusPillClass = "pill-mock";
        diffColorClass = "text-danger";
        diffPrefix = "-";
      }

      tr.innerHTML = `
        <td><strong>${item.date}</strong></td>
        <td>${formatINR(item.collection)}</td>
        <td>${formatINR(item.quota)}</td>
        <td>${formatINR(item.paid)}</td>
        <td><strong class="${diffColorClass}">${diffPrefix}${formatINR(item.diff)}</strong></td>
        <td><span class="pill ${statusPillClass}">${item.status}</span></td>
      `;
      settlementHistoryTableBody.appendChild(tr);
    });
  }

  /**
   * Dynamically add settlement entry (e.g. from Voice Co-Pilot)
   */
  function recordDailySettlement(collection, quota, paid) {
    const diff = paid - quota;
    let status = diff === 0 ? "MATCHED" : diff > 0 ? "DRIVER_SURPLUS" : "DUE_TO_OWNER";

    settlementState.history.unshift({
      date: "Today, Just Now",
      collection: Number(collection) || 1500,
      quota: Number(quota) || 500,
      paid: Number(paid) || 200,
      diff: diff,
      status: status
    });

    renderHistoryTable();
  }

  /**
   * Initialize Module Listeners
   */
  function initSettlementModule() {
    if (settlementCalcForm) {
      settlementCalcForm.addEventListener("submit", (e) => {
        e.preventDefault();
        computeReconciliation();
        if (window.showToast) {
          window.showToast("Reconciliation calculated successfully!", "info");
        }
      });
    }

    renderHistoryTable();
    computeReconciliation();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSettlementModule);
  } else {
    initSettlementModule();
  }

  // Export
  window.SettlementModule = {
    recordDailySettlement,
    computeReconciliation
  };

})();

