/**
 * T2T DRIVE — PASSENGER CLIENT INTERACTION SCRIPT
 * Lightweight, zero-account web app for passenger trip agreements,
 * change proposals, consent management, and receipt viewing.
 */

(function () {
  'use strict';

  // State
  let tripId = null;
  let token = null;
  let currentTrip = null;

  // DOM Elements
  const tripStatusBadge = document.getElementById("tripStatusBadge");
  const alertBox = document.getElementById("alertBox");
  const pickupText = document.getElementById("pickupText");
  const destinationText = document.getElementById("destinationText");
  const stopsContainer = document.getElementById("stopsContainer");
  const fareLabel = document.getElementById("fareLabel");
  const fareAmount = document.getElementById("fareAmount");
  const initialActionGroup = document.getElementById("initialActionGroup");
  const btnAgree = document.getElementById("btnAgree");
  const btnDecline = document.getElementById("btnDecline");

  const proposalCard = document.getElementById("proposalCard");
  const proposalDesc = document.getElementById("proposalDesc");
  const btnAcceptProposal = document.getElementById("btnAcceptProposal");
  const btnRejectProposal = document.getElementById("btnRejectProposal");

  const changeInput = document.getElementById("changeInput");
  const btnProposeDest = document.getElementById("btnProposeDest");

  const consentStatusText = document.getElementById("consentStatusText");
  const btnToggleConsent = document.getElementById("btnToggleConsent");

  const receiptAgreedFare = document.getElementById("receiptAgreedFare");
  const receiptPaidFare = document.getElementById("receiptPaidFare");
  const receiptOutstanding = document.getElementById("receiptOutstanding");
  const receiptStatus = document.getElementById("receiptStatus");
  const btnDispute = document.getElementById("btnDispute");

  function showAlert(msg, isError = false) {
    if (!alertBox) return;
    alertBox.textContent = msg;
    alertBox.className = `alert ${isError ? 'alert-danger' : 'alert-info'}`;
    alertBox.classList.remove("hidden");
    setTimeout(() => alertBox.classList.add("hidden"), 5000);
  }

  function getApiBase() {
    return window.location.origin;
  }

  async function apiRequest(endpoint, method = "GET", body = null) {
    const url = `${getApiBase()}${endpoint}`;
    const headers = {
      "Content-Type": "application/json",
      "X-Passenger-Token": token || ""
    };
    const options = { method, headers };
    if (body) {
      options.body = JSON.stringify(body);
    }
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok || data.success === false) {
      const err = (data.error && data.error.message) || `HTTP error ${res.status}`;
      throw new Error(err);
    }
    return data.data;
  }

  async function loadTripDetails() {
    try {
      const data = await apiRequest(`/api/passenger/trips/${tripId}?token=${encodeURIComponent(token)}`);
      currentTrip = data.trip;
      renderTrip();
    } catch (err) {
      showAlert(`Could not load trip: ${err.message}`, true);
    }
  }

  function renderTrip() {
    if (!currentTrip) return;

    // 1. Status Badge
    const state = currentTrip.state || "CREATED";
    tripStatusBadge.textContent = state.replace("_", " ");
    tripStatusBadge.className = `badge badge-${state.toLowerCase()}`;

    // 2. Locations
    pickupText.textContent = currentTrip.pickup_location || "—";
    destinationText.textContent = currentTrip.destination_location || "—";

    // 3. Stops
    stopsContainer.innerHTML = "";
    if (currentTrip.additional_stops && currentTrip.additional_stops.length > 0) {
      currentTrip.additional_stops.forEach((stop, i) => {
        const div = document.createElement("div");
        div.className = "route-item";
        div.innerHTML = `
          <div class="route-dot dot-stop"></div>
          <div>
            <div class="route-label">STOP ${i + 1}</div>
            <div class="route-val">${stop}</div>
          </div>
        `;
        stopsContainer.appendChild(div);
      });
    }

    // 4. Fares & Initial Action
    if (currentTrip.current_agreed_fare) {
      fareLabel.textContent = "AGREED FARE";
      fareAmount.textContent = `₹${currentTrip.current_agreed_fare}`;
      initialActionGroup.classList.add("hidden");
    } else {
      fareLabel.textContent = "PROPOSED FARE";
      fareAmount.textContent = `₹${currentTrip.initial_proposed_fare || "0.00"}`;
      if (state === "AGREEMENT_PENDING") {
        initialActionGroup.classList.remove("hidden");
      } else {
        initialActionGroup.classList.add("hidden");
      }
    }

    // 5. Active Proposals
    if (currentTrip.active_proposal && (
      currentTrip.active_proposal.status === "PROPOSED" ||
      currentTrip.active_proposal.status === "ACCEPTED_BY_DRIVER"
    )) {
      proposalCard.classList.remove("hidden");
      const prop = currentTrip.active_proposal;
      let desc = `Change proposed by ${prop.proposed_by}: `;
      if (prop.proposal_type === "DESTINATION_CHANGE") {
        desc += `New Destination: "${prop.proposed_value.destination_location}"`;
      } else if (prop.proposal_type === "ADD_STOP") {
        desc += `Additional Stop: "${prop.proposed_value.stop}"`;
      } else if (prop.proposal_type === "FARE_CHANGE") {
        desc += `Updated Fare: ₹${prop.proposed_value.agreed_fare}`;
      }
      proposalDesc.textContent = desc;
    } else {
      proposalCard.classList.add("hidden");
    }

    // 6. Consent Status
    const consent = currentTrip.consent_status || {};
    if (consent.is_active) {
      consentStatusText.textContent = "In-Cabin Listening: ACTIVE (Mutually Consented)";
      consentStatusText.style.color = "#16a34a";
      btnToggleConsent.textContent = "Stop / Withdraw";
      btnToggleConsent.className = "btn-outline";
    } else if (consent.passenger_consented) {
      consentStatusText.textContent = "Passenger Consented (Awaiting Driver)";
      consentStatusText.style.color = "#d97706";
      btnToggleConsent.textContent = "Withdraw";
      btnToggleConsent.className = "btn-outline";
    } else {
      consentStatusText.textContent = "In-Cabin Listening: OFF";
      consentStatusText.style.color = "#64748b";
      btnToggleConsent.textContent = "Grant Consent";
      btnToggleConsent.className = "btn-primary";
    }

    // 7. Payment Summary
    receiptAgreedFare.textContent = `₹${currentTrip.current_agreed_fare || currentTrip.initial_proposed_fare || "0.00"}`;
    receiptPaidFare.textContent = `₹${currentTrip.collected_amount || "0.00"}`;
    receiptOutstanding.textContent = `₹${currentTrip.outstanding_amount || "0.00"}`;
    receiptStatus.textContent = (currentTrip.payment_status || "UNPAID").replace("_", " ");
  }

  // Initialize
  function init() {
    const params = new URLSearchParams(window.location.search);
    tripId = params.get("trip_id");
    token = params.get("token");

    if (!tripId || !token) {
      showAlert("Invalid or missing passenger access link.", true);
      return;
    }

    // Attach Event Listeners
    if (btnAgree) {
      btnAgree.addEventListener("click", async () => {
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/agreement`, "POST", { accepted: true });
          showAlert("Trip agreement accepted! Enjoy your journey.");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnDecline) {
      btnDecline.addEventListener("click", async () => {
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/agreement`, "POST", { accepted: false });
          showAlert("Trip proposal declined.");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnAcceptProposal) {
      btnAcceptProposal.addEventListener("click", async () => {
        if (!currentTrip || !currentTrip.active_proposal) return;
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/respond-proposal`, "POST", {
            proposal_id: currentTrip.active_proposal.proposal_id,
            accepted: true
          });
          showAlert("Change accepted!");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnRejectProposal) {
      btnRejectProposal.addEventListener("click", async () => {
        if (!currentTrip || !currentTrip.active_proposal) return;
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/respond-proposal`, "POST", {
            proposal_id: currentTrip.active_proposal.proposal_id,
            accepted: false
          });
          showAlert("Change rejected. Previous agreement preserved.");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnProposeDest) {
      btnProposeDest.addEventListener("click", async () => {
        const val = changeInput.value.trim();
        if (!val) {
          showAlert("Please enter a new destination or stop name.", true);
          return;
        }
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/propose-change`, "POST", {
            proposal_type: "DESTINATION_CHANGE",
            proposed_value: { destination_location: val },
            reason: "Proposed by passenger via web app"
          });
          changeInput.value = "";
          showAlert("Destination change proposed. Awaiting driver confirmation.");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnToggleConsent) {
      btnToggleConsent.addEventListener("click", async () => {
        const currentConsent = currentTrip && currentTrip.consent_status && currentTrip.consent_status.passenger_consented;
        const newConsent = !currentConsent;
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/consent`, "POST", { consent: newConsent });
          showAlert(`Listening consent ${newConsent ? 'granted' : 'withdrawn'}.`);
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    if (btnDispute) {
      btnDispute.addEventListener("click", async () => {
        const reason = prompt("Please describe the dispute (fare, route, payment):");
        if (!reason || !reason.strip()) return;
        try {
          await apiRequest(`/api/passenger/trips/${tripId}/dispute`, "POST", { reason });
          showAlert("Dispute flagged. Support and trip history logged.");
          loadTripDetails();
        } catch (e) {
          showAlert(e.message, true);
        }
      });
    }

    loadTripDetails();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
