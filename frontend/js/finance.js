/**
 * T2T DRIVE — FINANCE MODULE
 * KPI Counters, Pure Vanilla HTML5 Canvas Charts (Bar & Donut),
 * Transaction Ledger filtering, and dynamic voice sync.
 */

(function () {
  'use strict';

  // DOM Elements
  const kpiTodayIncome = document.getElementById("kpiTodayIncome");
  const kpiTodayExpenses = document.getElementById("kpiTodayExpenses");
  const kpiTodayOwner = document.getElementById("kpiTodayOwner");
  const kpiTodayNet = document.getElementById("kpiTodayNet");
  const financeBarChart = document.getElementById("financeBarChart");
  const financeDonutChart = document.getElementById("financeDonutChart");
  const donutCenterTotal = document.getElementById("donutCenterTotal");
  const donutLegendList = document.getElementById("donutLegendList");
  const transactionsTableBody = document.getElementById("transactionsTableBody");
  const txFilterGroup = document.getElementById("txFilterGroup");
  const txCountSubtitle = document.getElementById("txCountSubtitle");
  const periodButtons = document.querySelectorAll(".period-btn");

  // In-Memory State
  let financeState = {
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
    labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
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
  };

  let activePeriod = "weekly";
  let activeFilter = "all";

  /**
   * Currency formatter helper
   */
  function formatINR(amount) {
    return "₹" + Number(amount || 0).toLocaleString("en-IN");
  }

  /**
   * Animated Number Counter
   */
  function animateValue(element, target, prefix = "₹", duration = 600) {
    if (!element) return;
    const start = 0;
    const startTime = performance.now();

    function step(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const current = Math.round(start + (target - start) * (1 - Math.pow(1 - progress, 3)));
      element.textContent = prefix + current.toLocaleString("en-IN");

      if (progress < 1) {
        requestAnimationFrame(step);
      }
    }
    requestAnimationFrame(step);
  }

  /**
   * Render KPI Cards
   */
  function renderKpiCards() {
    const data = activePeriod === "monthly" 
      ? financeState.monthly 
      : activePeriod === "weekly" 
        ? financeState.weekly 
        : financeState.today;

    animateValue(kpiTodayIncome, data.income);
    animateValue(kpiTodayExpenses, data.expenses);
    animateValue(kpiTodayOwner, data.owner_payments);
    animateValue(kpiTodayNet, data.net_balance);
  }

  /**
   * Draw Vanilla HTML5 Canvas Bar Chart
   */
  function drawBarChart() {
    if (!financeBarChart) return;
    const canvas = financeBarChart;
    const ctx = canvas.getContext("2d");

    // Responsive Canvas dimensions
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width || 550;
    canvas.height = 260;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const labels = financeState.labels;
    const incomes = financeState.income_series;
    const expenses = financeState.expense_series;

    const maxVal = Math.max(...incomes, ...expenses, 2000) * 1.15;
    const paddingLeft = 45;
    const paddingBottom = 35;
    const paddingTop = 20;
    const paddingRight = 20;

    const chartW = w - paddingLeft - paddingRight;
    const chartH = h - paddingTop - paddingBottom;
    const groupCount = labels.length;
    const groupW = chartW / groupCount;
    const barW = Math.max(groupW * 0.32, 10);

    // Draw horizontal gridlines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#6b7280";
    ctx.font = "11px 'JetBrains Mono', monospace";
    ctx.textAlign = "right";

    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const yVal = Math.round((maxVal / steps) * i);
      const yPos = paddingTop + chartH - (chartH * (i / steps));

      ctx.beginPath();
      ctx.moveTo(paddingLeft, yPos);
      ctx.lineTo(w - paddingRight, yPos);
      ctx.stroke();

      ctx.fillText("₹" + (yVal >= 1000 ? (yVal / 1000).toFixed(1) + "k" : yVal), paddingLeft - 8, yPos + 4);
    }

    // Draw Bars
    labels.forEach((label, i) => {
      const xCenter = paddingLeft + (i * groupW) + (groupW / 2);

      // Income bar
      const incVal = incomes[i] || 0;
      const incH = (incVal / maxVal) * chartH;
      const incX = xCenter - barW - 2;
      const incY = paddingTop + chartH - incH;

      ctx.fillStyle = "#10b981"; // Earnings Green
      ctx.beginPath();
      ctx.roundRect(incX, incY, barW, incH, [4, 4, 0, 0]);
      ctx.fill();

      // Expense bar
      const expVal = expenses[i] || 0;
      const expH = (expVal / maxVal) * chartH;
      const expX = xCenter + 2;
      const expY = paddingTop + chartH - expH;

      ctx.fillStyle = "#ef4444"; // Expense Red
      ctx.beginPath();
      ctx.roundRect(expX, expY, barW, expH, [4, 4, 0, 0]);
      ctx.fill();

      // X Label
      ctx.fillStyle = "#9ca3af";
      ctx.font = "11px 'Plus Jakarta Sans', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, xCenter, h - 12);
    });
  }

  /**
   * Draw Vanilla Canvas Donut Chart
   */
  function drawDonutChart() {
    if (!financeDonutChart) return;
    const canvas = financeDonutChart;
    const ctx = canvas.getContext("2d");

    canvas.width = 220;
    canvas.height = 220;

    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const outerRadius = 85;
    const innerRadius = 55;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const categories = financeState.category_breakdown;
    const total = categories.reduce((sum, item) => sum + item.value, 0);

    if (donutCenterTotal) donutCenterTotal.textContent = formatINR(total);

    let startAngle = -Math.PI / 2;

    categories.forEach(item => {
      const sliceAngle = (item.value / total) * (2 * Math.PI);

      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(centerX, centerY, outerRadius, startAngle, startAngle + sliceAngle);
      ctx.arc(centerX, centerY, innerRadius, startAngle + sliceAngle, startAngle, true);
      ctx.closePath();
      ctx.fill();

      startAngle += sliceAngle;
    });

    // Populate Legend List
    if (donutLegendList) {
      donutLegendList.innerHTML = "";
      categories.forEach(item => {
        const pct = Math.round((item.value / total) * 100);
        const row = document.createElement("div");
        row.className = "donut-item";
        row.innerHTML = `
          <div class="donut-item-left">
            <span class="donut-dot" style="background-color: ${item.color}"></span>
            <span>${item.name} (${pct}%)</span>
          </div>
          <span class="donut-item-val">${formatINR(item.value)}</span>
        `;
        donutLegendList.appendChild(row);
      });
    }
  }

  /**
   * Render Transactions Ledger Table
   */
  function renderTransactions() {
    if (!transactionsTableBody) return;
    transactionsTableBody.innerHTML = "";

    const filtered = financeState.transactions.filter(tx => {
      if (activeFilter === "all") return true;
      return tx.type === activeFilter;
    });

    if (txCountSubtitle) {
      txCountSubtitle.textContent = `Showing ${filtered.length} entries for "${activeFilter}" filter`;
    }

    if (filtered.length === 0) {
      transactionsTableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center;padding:24px;color:var(--text-subtle);">
            No transactions found for filter "${activeFilter}".
          </td>
        </tr>
      `;
      return;
    }

    filtered.forEach(tx => {
      const tr = document.createElement("tr");

      let badgeClass = "pill-live";
      let amountClass = "text-success";
      let prefix = "+ ";

      if (tx.type === "expense") {
        badgeClass = "pill-mock";
        amountClass = "text-danger";
        prefix = "- ";
      } else if (tx.type === "owner") {
        badgeClass = "pill-beta";
        amountClass = "text-warning";
        prefix = "- ";
      }

      tr.innerHTML = `
        <td><strong>${tx.date}</strong></td>
        <td><span class="pill ${badgeClass}">${tx.type.toUpperCase()}</span></td>
        <td>${tx.description}</td>
        <td><span class="kpi-sub">${tx.mode || 'Cash'}</span></td>
        <td class="text-right font-mono"><strong class="${amountClass}">${prefix}${formatINR(tx.amount)}</strong></td>
      `;
      transactionsTableBody.appendChild(tr);
    });
  }

  /**
   * Add new transaction dynamically (e.g. from Voice Co-Pilot)
   */
  function addTransaction(tx) {
    const newTx = {
      id: "tx-" + Date.now(),
      date: "Just Now",
      type: tx.type || "income",
      description: tx.description || "Voice Entry",
      amount: Number(tx.amount) || 0,
      mode: tx.mode || "Cash"
    };

    financeState.transactions.unshift(newTx);

    // Update Today metrics
    if (newTx.type === "income") {
      financeState.today.income += newTx.amount;
    } else if (newTx.type === "expense") {
      financeState.today.expenses += newTx.amount;
    } else if (newTx.type === "owner") {
      financeState.today.owner_payments += newTx.amount;
    }

    financeState.today.net_balance = financeState.today.income - financeState.today.expenses - financeState.today.owner_payments;

    renderKpiCards();
    renderTransactions();
    drawBarChart();
  }

  /**
   * Fetch from backend or mock
   */
  async function loadFinanceData() {
    try {
      const res = await window.API.getSummary(activePeriod);
      if (res && res.today) {
        financeState = {
          ...financeState,
          today: res.today,
          weekly: res.weekly || financeState.weekly,
          monthly: res.monthly || financeState.monthly,
          transactions: res.transactions || financeState.transactions,
          category_breakdown: res.category_breakdown || financeState.category_breakdown,
          income_series: res.income_series || financeState.income_series,
          expense_series: res.expense_series || financeState.expense_series
        };
      }
    } catch (err) {
      console.warn("Could not fetch remote finance data, utilizing local cache:", err);
    }

    renderKpiCards();
    drawBarChart();
    drawDonutChart();
    renderTransactions();
  }

  /**
   * Setup Listeners
   */
  function initFinanceModule() {
    // Period Toggles
    periodButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        periodButtons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activePeriod = btn.getAttribute("data-period");
        renderKpiCards();
        drawBarChart();
      });
    });

    // Transaction Filters
    if (txFilterGroup) {
      const filterPills = txFilterGroup.querySelectorAll(".filter-pill");
      filterPills.forEach(pill => {
        pill.addEventListener("click", () => {
          filterPills.forEach(p => p.classList.remove("active"));
          pill.classList.add("active");
          activeFilter = pill.getAttribute("data-filter");
          renderTransactions();
        });
      });
    }

    // Redraw charts on resize or view switch
    window.addEventListener("resize", () => {
      drawBarChart();
    });

    window.addEventListener("viewChanged", (e) => {
      if (e.detail && e.detail.view === "finance") {
        setTimeout(() => {
          drawBarChart();
          drawDonutChart();
        }, 50);
      }
    });

    loadFinanceData();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFinanceModule);
  } else {
    initFinanceModule();
  }

  // Export
  window.FinanceModule = {
    addTransaction,
    loadFinanceData
  };

})();

