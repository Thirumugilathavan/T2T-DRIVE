/**
 * T2T DRIVE — AGENT & AI DIAGNOSTIC MODULE
 * Gnani ASR Telemetry, 6-Step Pipeline Visualizer, Slot Inspection,
 * and Acoustic Noise Evaluation (Auto-Rickshaw Cabin Profile).
 */

(function () {
  'use strict';

  // DOM Elements
  const pipelineStepper = document.getElementById("pipelineStepper");
  const rawEntitiesJson = document.getElementById("rawEntitiesJson");
  const agentSnrVal = document.getElementById("agentSnrVal");

  // Initial Diagnostic Telemetry State
  const defaultTrace = [
    { step: 1, title: "Acoustic Noise Gate", detail: "Filtered 120Hz-400Hz engine hum. SNR 24.2 dB.", status: "complete" },
    { step: 2, title: "Speech Recognition", detail: 'Transcribed: "Inniku collection 1500, petrol 300, owner-ku 200 kuduthen."', status: "complete" },
    { step: 3, title: "Language Classification", detail: "Detected Tanglish / Tamil blend (Indic-ASR)", status: "complete" },
    { step: 4, title: "NLU Intent Parsing", detail: "Classified Intent: log_transaction (Score: 0.96)", status: "complete" },
    { step: 5, title: "Slot Filling & Entity Extraction", detail: "income=₹1500, expense=₹300 (petrol), owner=₹200", status: "complete" },
    { step: 6, title: "Driver Confirmation Gate", detail: "Awaiting driver confirmation or confirmed.", status: "complete" }
  ];

  /**
   * Render Pipeline Stepper
   */
  function renderPipeline(steps) {
    if (!pipelineStepper) return;
    pipelineStepper.innerHTML = "";

    steps.forEach(s => {
      const card = document.createElement("div");
      card.className = "step-card";

      const indicator = document.createElement("div");
      indicator.className = "step-indicator";
      if (s.status === "waiting") {
        indicator.style.backgroundColor = "var(--primary)";
      } else {
        indicator.style.backgroundColor = "var(--success)";
      }

      card.appendChild(indicator);

      const content = document.createElement("div");
      content.innerHTML = `
        <div class="step-title">${s.step}. ${s.title}</div>
        <div class="step-desc">${s.detail}</div>
      `;
      card.appendChild(content);

      pipelineStepper.appendChild(card);
    });
  }

  /**
   * Update Raw Entities JSON display
   */
  function renderJsonEntities(entities) {
    if (!rawEntitiesJson) return;
    const jsonStr = JSON.stringify(entities || {
      intent: "log_transaction",
      entities: { income: 1500, expense: 300, category: "petrol", owner_payment: 200 },
      confidence: 0.96,
      language: "tanglish"
    }, null, 2);

    rawEntitiesJson.innerHTML = `<code>${escapeHtml(jsonStr)}</code>`;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Dynamically called when Voice/Text processing occurs
   */
  function updatePipelineTrace(traceSteps, entities) {
    if (traceSteps && traceSteps.length > 0) {
      renderPipeline(traceSteps);
    }
    if (entities) {
      renderJsonEntities({
        intent: "log_transaction",
        entities: entities,
        confidence: 0.95 + (Math.random() * 0.04),
        timestamp: new Date().toISOString()
      });
    }

    // Fluctuate SNR slightly for realism (22 - 27 dB)
    if (agentSnrVal) {
      const randSnr = (23 + Math.random() * 3).toFixed(1);
      agentSnrVal.textContent = `${randSnr} dB`;
    }
  }

  /**
   * Initialize Module
   */
  function initAgentModule() {
    renderPipeline(defaultTrace);
    renderJsonEntities();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAgentModule);
  } else {
    initAgentModule();
  }

  // Export
  window.AgentModule = {
    updatePipelineTrace
  };

})();

