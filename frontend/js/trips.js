/**
 * T2T DRIVE — DRIVER TRIPS & PASSENGER AGREEMENT CONTROLLER
 * Handles trip creation, QR code visualization, dual-consent continuous listening,
 * in-trip modification proposals, and financial reconciliation.
 */

(function () {
  'use strict';

  let currentActiveTrip = null;

  function showToast(msg, type = 'info') {
    if (window.showToast) {
      window.showToast(msg, type);
    } else {
      console.log(`[TOAST ${type}]`, msg);
    }
  }

  function getAuthHeader() {
    const token = localStorage.getItem('t2t_token') || 'dev-driver-token';
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  }

  /**
   * Load active trip for driver
   */
  async function loadActiveTrip() {
    try {
      const res = await fetch('/api/trips/active', {
        headers: getAuthHeader()
      });
      const data = await res.json();
      if (res.ok && data.success && data.data && data.data.trip) {
        currentActiveTrip = data.data.trip;
        renderActiveTrip(currentActiveTrip, data.data.passenger_access);
      } else {
        currentActiveTrip = null;
        renderNoActiveTrip();
      }
    } catch (e) {
      console.warn('Could not load active trip:', e);
      renderNoActiveTrip();
    }
  }

  function renderNoActiveTrip() {
    const noPrompt = document.getElementById('noActiveTripPrompt');
    const details = document.getElementById('activeTripDetails');
    const badge = document.getElementById('tripStatusBadge');
    const navBadge = document.getElementById('activeTripBadge');

    if (noPrompt) noPrompt.classList.remove('hidden');
    if (details) details.classList.add('hidden');
    if (badge) {
      badge.textContent = 'NO ACTIVE TRIP';
      badge.className = 'card-badge secondary-badge';
    }
    if (navBadge) {
      navBadge.textContent = 'IDLE';
      navBadge.className = 'nav-badge';
    }
  }

  function renderActiveTrip(trip, passengerAccess) {
    const noPrompt = document.getElementById('noActiveTripPrompt');
    const details = document.getElementById('activeTripDetails');
    const badge = document.getElementById('tripStatusBadge');
    const navBadge = document.getElementById('activeTripBadge');

    if (noPrompt) noPrompt.classList.add('hidden');
    if (details) details.classList.remove('hidden');

    if (badge) {
      badge.textContent = trip.status;
      badge.className = `card-badge ${trip.status === 'AGREED' || trip.status === 'STARTED' ? 'success-badge' : 'info-badge'}`;
    }
    if (navBadge) {
      navBadge.textContent = trip.status;
      navBadge.className = 'nav-badge success';
    }

    const elId = document.getElementById('activeTripId');
    const elDest = document.getElementById('activeTripDestination');
    const elFare = document.getElementById('activeTripFare');
    const elOut = document.getElementById('activeTripOutstanding');

    if (elId) elId.textContent = trip.trip_id;
    if (elDest) elDest.textContent = trip.current_agreement?.destination || trip.initial_destination || '—';
    if (elFare) elFare.textContent = `₹${trip.current_agreement?.agreed_fare || trip.initial_fare || '0.00'}`;
    if (elOut) elOut.textContent = `₹${trip.outstanding_amount || '0.00'}`;

    // Consent & Listening
    const driverConsent = trip.consent_state?.driver_consented;
    const passengerConsent = trip.consent_state?.passenger_consented;
    const listeningActive = trip.consent_state?.continuous_listening_active;

    const elDriverConsent = document.getElementById('driverConsentLabel');
    const elPassConsent = document.getElementById('passengerConsentLabel');
    const elListening = document.getElementById('listeningModeLabel');

    if (elDriverConsent) {
      elDriverConsent.textContent = driverConsent ? 'GRANTED' : 'OFF';
      elDriverConsent.className = driverConsent ? 'text-success' : 'text-danger';
    }
    if (elPassConsent) {
      elPassConsent.textContent = passengerConsent ? 'GRANTED' : 'OFF';
      elPassConsent.className = passengerConsent ? 'text-success' : 'text-danger';
    }
    if (elListening) {
      elListening.textContent = listeningActive ? 'STREAMING ACTIVE' : 'PUSH-TO-TALK ONLY';
      elListening.className = listeningActive ? 'badge success' : 'badge warning';
    }

    const startBtn = document.getElementById('startContinuousBtn');
    const stopBtn = document.getElementById('stopContinuousBtn');
    if (startBtn) startBtn.disabled = !(driverConsent && passengerConsent) || listeningActive;
    if (stopBtn) stopBtn.disabled = !listeningActive;

    // QR & Link
    if (passengerAccess) {
      const qrContainer = document.getElementById('tripQrSvgContainer');
      const urlInput = document.getElementById('passengerAccessUrlInput');
      if (qrContainer && passengerAccess.qr_code_svg) {
        qrContainer.innerHTML = passengerAccess.qr_code_svg;
      }
      if (urlInput && passengerAccess.passenger_url) {
        urlInput.value = passengerAccess.passenger_url;
      }
    }

    // Active proposal banner
    const notice = document.getElementById('activeProposalNotice');
    if (notice) {
      if (trip.active_proposal && trip.active_proposal.status === 'PENDING') {
        const p = trip.active_proposal;
        notice.classList.remove('hidden');
        notice.innerHTML = `
          <strong>Proposal Pending:</strong> ${p.proposal_type} proposed by ${p.proposer_role}.
          Changes: ${JSON.stringify(p.proposed_changes)}.
          ${p.proposer_role === 'PASSENGER' ? '<div style="margin-top:0.4rem;"><button class="btn-sm btn-success" id="acceptProposalBtn">Accept</button> <button class="btn-sm btn-danger" id="rejectProposalBtn">Reject</button></div>' : '<em>Waiting for passenger response.</em>'}
        `;
        const acceptBtn = document.getElementById('acceptProposalBtn');
        const rejectBtn = document.getElementById('rejectProposalBtn');
        if (acceptBtn) acceptBtn.onclick = () => respondToProposal(trip.trip_id, true);
        if (rejectBtn) rejectBtn.onclick = () => respondToProposal(trip.trip_id, false);
      } else {
        notice.classList.add('hidden');
      }
    }
  }

  async function createTrip(e) {
    if (e) e.preventDefault();
    const dest = document.getElementById('newTripDestination')?.value?.trim();
    const fare = document.getElementById('newTripFare')?.value?.trim();
    const veh = document.getElementById('newTripVehicle')?.value?.trim() || 'TN-01-AB-1234';

    if (!dest || !fare) {
      showToast('Please enter both destination and agreed fare.', 'warning');
      return;
    }

    try {
      const res = await fetch('/api/trips', {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({
          destination: dest,
          initial_fare: parseFloat(fare),
          vehicle_id: veh
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Trip created and passenger QR generated!', 'success');
        currentActiveTrip = data.data.trip;
        renderActiveTrip(currentActiveTrip, data.data.passenger_access);
      } else {
        showToast(data.message || 'Failed to create trip', 'danger');
      }
    } catch (err) {
      showToast('Error creating trip: ' + err.message, 'danger');
    }
  }

  async function toggleDriverConsent() {
    if (!currentActiveTrip) return;
    const current = currentActiveTrip.consent_state?.driver_consented || false;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/consent`, {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({ consented: !current })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`Driver consent updated to ${!current ? 'GRANTED' : 'OFF'}`, 'info');
        loadActiveTrip();
      }
    } catch (err) {
      showToast('Failed to toggle consent', 'danger');
    }
  }

  async function startContinuousListening() {
    if (!currentActiveTrip) return;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/listening/start`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Continuous listening started', 'success');
        loadActiveTrip();
      } else {
        showToast(data.message || 'Cannot start continuous listening', 'warning');
      }
    } catch (err) {
      showToast('Failed to start continuous listening', 'danger');
    }
  }

  async function stopContinuousListening() {
    if (!currentActiveTrip) return;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/listening/stop`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Continuous listening stopped', 'info');
        loadActiveTrip();
      }
    } catch (err) {
      showToast('Failed to stop continuous listening', 'danger');
    }
  }

  async function startTrip() {
    if (!currentActiveTrip) return;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/start`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Trip is now STARTED', 'success');
        loadActiveTrip();
      } else {
        showToast(data.message || 'Failed to start trip', 'danger');
      }
    } catch (err) {
      showToast('Error starting trip', 'danger');
    }
  }

  async function completeTrip() {
    if (!currentActiveTrip) return;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/complete`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Trip COMPLETED successfully', 'success');
        loadActiveTrip();
      } else {
        showToast(data.message || 'Failed to complete trip', 'danger');
      }
    } catch (err) {
      showToast('Error completing trip', 'danger');
    }
  }

  async function cancelTrip() {
    if (!currentActiveTrip) return;
    if (!confirm('Are you sure you want to cancel this trip?')) return;
    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/cancel`, {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({ reason: 'Driver cancelled' })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Trip cancelled', 'info');
        loadActiveTrip();
      } else {
        showToast(data.message || 'Failed to cancel trip', 'danger');
      }
    } catch (err) {
      showToast('Error cancelling trip', 'danger');
    }
  }

  async function proposeChange(e) {
    if (e) e.preventDefault();
    if (!currentActiveTrip) {
      showToast('No active trip to propose changes for', 'warning');
      return;
    }
    const type = document.getElementById('proposalTypeSelect')?.value;
    const val = document.getElementById('proposalValueInput')?.value?.trim();
    const reason = document.getElementById('proposalReasonInput')?.value?.trim();

    if (!val) {
      showToast('Please enter the proposal value', 'warning');
      return;
    }

    const proposedChanges = {};
    if (type === 'DESTINATION_CHANGE') proposedChanges.destination = val;
    else if (type === 'ADD_STOP') proposedChanges.stop_name = val;
    else if (type === 'FARE_CHANGE') proposedChanges.fare = parseFloat(val);

    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/propose-change`, {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({
          proposal_type: type,
          proposed_changes: proposedChanges,
          reason: reason
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Change proposal sent to passenger!', 'success');
        document.getElementById('proposalValueInput').value = '';
        loadActiveTrip();
      } else {
        showToast(data.message || 'Failed to submit proposal', 'danger');
      }
    } catch (err) {
      showToast('Error submitting proposal', 'danger');
    }
  }

  async function respondToProposal(tripId, accept) {
    try {
      const res = await fetch(`/api/trips/${tripId}/respond-proposal`, {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({ accept: accept })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`Proposal ${accept ? 'ACCEPTED' : 'REJECTED'}`, 'info');
        loadActiveTrip();
      }
    } catch (err) {
      showToast('Error responding to proposal', 'danger');
    }
  }

  async function recordPayment(e) {
    if (e) e.preventDefault();
    if (!currentActiveTrip) {
      showToast('No active trip to collect payment for', 'warning');
      return;
    }
    const amt = document.getElementById('tripPaymentAmount')?.value;
    const method = document.getElementById('tripPaymentMethod')?.value || 'CASH';

    if (!amt || parseFloat(amt) <= 0) {
      showToast('Please enter a valid payment amount', 'warning');
      return;
    }

    const idempotencyKey = `PAY_${currentActiveTrip.trip_id}_${Date.now()}`;

    try {
      const res = await fetch(`/api/trips/${currentActiveTrip.trip_id}/payments`, {
        method: 'POST',
        headers: getAuthHeader(),
        body: JSON.stringify({
          amount: parseFloat(amt),
          payment_method: method,
          idempotency_key: idempotencyKey
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`Payment of ₹${amt} recorded successfully!`, 'success');
        document.getElementById('tripPaymentAmount').value = '';
        loadActiveTrip();
      } else {
        showToast(data.message || 'Failed to record payment', 'danger');
      }
    } catch (err) {
      showToast('Error recording payment: ' + err.message, 'danger');
    }
  }

  // Setup Event Listeners
  document.addEventListener('DOMContentLoaded', () => {
    const createForm = document.getElementById('createTripForm');
    if (createForm) createForm.onsubmit = createTrip;

    const refreshBtn = document.getElementById('refreshTripBtn');
    if (refreshBtn) refreshBtn.onclick = loadActiveTrip;

    const consentBtn = document.getElementById('driverConsentToggleBtn');
    if (consentBtn) consentBtn.onclick = toggleDriverConsent;

    const startContBtn = document.getElementById('startContinuousBtn');
    if (startContBtn) startContBtn.onclick = startContinuousListening;

    const stopContBtn = document.getElementById('stopContinuousBtn');
    if (stopContBtn) stopContBtn.onclick = stopContinuousListening;

    const startTrpBtn = document.getElementById('startTripBtn');
    if (startTrpBtn) startTrpBtn.onclick = startTrip;

    const compTrpBtn = document.getElementById('completeTripBtn');
    if (compTrpBtn) compTrpBtn.onclick = completeTrip;

    const canTrpBtn = document.getElementById('cancelTripBtn');
    if (canTrpBtn) canTrpBtn.onclick = cancelTrip;

    const propForm = document.getElementById('proposeTripChangeForm');
    if (propForm) propForm.onsubmit = proposeChange;

    const payForm = document.getElementById('recordTripPaymentForm');
    if (payForm) payForm.onsubmit = recordPayment;

    const copyBtn = document.getElementById('copyPassengerUrlBtn');
    if (copyBtn) {
      copyBtn.onclick = () => {
        const inp = document.getElementById('passengerAccessUrlInput');
        if (inp && inp.value) {
          navigator.clipboard.writeText(inp.value).then(() => {
            showToast('Passenger link copied to clipboard!', 'info');
          });
        }
      };
    }

    // Auto load active trip on startup
    loadActiveTrip();
  });

  window.TripsModule = {
    loadActiveTrip,
    createTrip,
    startTrip,
    completeTrip,
    recordPayment
  };

})();
