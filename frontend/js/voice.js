/**
 * T2T DRIVE — VOICE CO-PILOT MODULE
 * Voice recording, Web Audio API analysis, noise-aware visualizer,
 * slot confirmation, audio file ingestion, and conversational flow.
 */

(function () {
  'use strict';

  // DOM Elements
  const pttBtn = document.getElementById("pttBtn");
  const pttLabel = document.getElementById("pttLabel");
  const pttTimer = document.getElementById("pttTimer");
  const waveformCanvas = document.getElementById("waveformCanvas");
  const visualizerSubtext = document.getElementById("visualizerSubtext");
  const audioFileInput = document.getElementById("audioFileInput");
  const audioFileNameDisplay = document.getElementById("audioFileNameDisplay");
  const manualVoiceInput = document.getElementById("manualVoiceInput");
  const submitManualVoiceBtn = document.getElementById("submitManualVoiceBtn");
  const liveTranscriptBox = document.getElementById("liveTranscriptBox");
  const detectedLangText = document.getElementById("detectedLangText");
  const transactionConfirmContainer = document.getElementById("transactionConfirmContainer");
  const chipIncomeVal = document.getElementById("chipIncomeVal");
  const chipExpenseVal = document.getElementById("chipExpenseVal");
  const chipOwnerVal = document.getElementById("chipOwnerVal");
  const chipNetVal = document.getElementById("chipNetVal");
  const confirmYesBtn = document.getElementById("confirmYesBtn");
  const confirmNoBtn = document.getElementById("confirmNoBtn");
  const ttsAudioPlayer = document.getElementById("ttsAudioPlayer");
  const ttsTextPreview = document.getElementById("ttsTextPreview");
  const chatStreamBox = document.getElementById("chatStreamBox");
  const clearChatHistoryBtn = document.getElementById("clearChatHistoryBtn");
  const samplePills = document.querySelectorAll(".sample-pill");
  const voiceAlertBox = document.getElementById("voiceAlertBox");

  // State Variables
  let mediaRecorder = null;
  let audioChunks = [];
  let isRecording = false;
  let recordTimerInterval = null;
  let recordStartTime = 0;
  let audioContext = null;
  let analyser = null;
  let animationFrameId = null;
  let currentPendingId = null;
  let currentExtractedEntities = null;

  /**
   * Format milliseconds into MM:SS
   */
  function formatTime(ms) {
    const totalSecs = Math.floor(ms / 1000);
    const mins = String(Math.floor(totalSecs / 60)).padStart(2, '0');
    const secs = String(totalSecs % 60).padStart(2, '0');
    return `${mins}:${secs}`;
  }

  /**
   * Display Alert in Voice card
   */
  function showVoiceAlert(message, type = "info") {
    if (!voiceAlertBox) return;
    voiceAlertBox.className = `alert-box ${type}`;
    voiceAlertBox.textContent = message;
    voiceAlertBox.classList.remove("hidden");
    setTimeout(() => {
      voiceAlertBox.classList.add("hidden");
    }, 5000);
  }

  /**
   * Draw Idle Waveform on Canvas
   */
  function drawIdleWaveform() {
    if (!waveformCanvas) return;
    const ctx = waveformCanvas.getContext("2d");
    const width = waveformCanvas.width;
    const height = waveformCanvas.height;

    ctx.clearRect(0, 0, width, height);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(245, 158, 11, 0.4)";
    ctx.beginPath();

    const midY = height / 2;
    ctx.moveTo(0, midY);

    for (let x = 0; x < width; x += 6) {
      const y = midY + Math.sin(x * 0.05) * 4;
      ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  /**
   * Draw Live Web Audio Visualizer
   */
  function drawLiveWaveform() {
    if (!analyser || !waveformCanvas) return;

    const ctx = waveformCanvas.getContext("2d");
    const width = waveformCanvas.width;
    const height = waveformCanvas.height;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function render() {
      if (!isRecording) return;
      animationFrameId = requestAnimationFrame(render);

      analyser.getByteTimeDomainData(dataArray);

      ctx.fillStyle = "rgba(9, 14, 26, 0.3)";
      ctx.fillRect(0, 0, width, height);

      ctx.lineWidth = 2.5;
      ctx.strokeStyle = "#f59e0b"; // Golden road waveform
      ctx.beginPath();

      const sliceWidth = (width * 1.0) / bufferLength;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        const v = dataArray[i] / 128.0;
        const y = (v * height) / 2;

        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);

        x += sliceWidth;
      }

      ctx.lineTo(width, height / 2);
      ctx.stroke();
    }

    render();
  }

  /**
   * Start Microphone Capture
   */
  async function startRecording() {
    try {
      audioChunks = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Setup Web Audio Analyser
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      // Setup MediaRecorder
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
        stream.getTracks().forEach(track => track.stop());
        await processAudioInput(audioBlob);
      };

      mediaRecorder.start();
      isRecording = true;

      // Update UI
      pttBtn.classList.add("recording");
      pttLabel.textContent = "Listening... Tap to Stop";
      visualizerSubtext.textContent = "🎙️ Live Road Mic Active — Noise Gate: Filtering Low RPM";
      recordStartTime = Date.now();
      pttTimer.textContent = "00:00";

      recordTimerInterval = setInterval(() => {
        pttTimer.textContent = formatTime(Date.now() - recordStartTime);
      }, 1000);

      drawLiveWaveform();
      beepSound(440, 0.08); // Friendly record start beep

    } catch (err) {
      console.warn("Microphone access error:", err);
      showVoiceAlert("Microphone permission denied or unavailable. You can use text input or upload an audio file.", "warning");
      visualizerSubtext.textContent = "Mic permission not granted. Use text prompt.";
    }
  }

  /**
   * Stop Microphone Capture
   */
  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }

    clearInterval(recordTimerInterval);
    if (animationFrameId) cancelAnimationFrame(animationFrameId);

    pttBtn.classList.remove("recording");
    pttLabel.textContent = "Processing...";
    visualizerSubtext.textContent = "Analyzing Indic speech & extracting numbers...";
    beepSound(880, 0.06); // Stop beep
  }

  /**
   * Synthesize Audio Beep using Web Audio (no external assets needed)
   */
  function beepSound(freq = 600, duration = 0.1) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + duration);
    } catch (e) {
      // AudioContext policy fallback
    }
  }

  /**
   * Process Audio Input via API
   */
  async function processAudioInput(blob) {
    try {
      visualizerSubtext.textContent = "Transcribing with Gnani Indic-ASR...";
      const lang = window.currentLanguage || "tanglish";

      const res = await window.API.transcribe(blob, lang);

      pttLabel.textContent = "Tap & Speak";
      visualizerSubtext.textContent = "Microphone idle. Speech transcribed successfully!";
      drawIdleWaveform();

      if (res && res.transcript) {
        handleUserTextSubmission(res.transcript, res.detected_language);
      }
    } catch (err) {
      console.error("Transcription error:", err);
      pttLabel.textContent = "Tap & Speak";
      visualizerSubtext.textContent = "Transcription error: " + err.message;
      showVoiceAlert("Transcription failed. Fallback to manual text input.", "danger");
      drawIdleWaveform();
    }
  }

  /**
   * Process Natural Language Prompt (from voice or text)
   */
  async function handleUserTextSubmission(text, detectedLanguage = null) {
    if (!text || !text.trim()) return;

    // Put into transcript box
    if (liveTranscriptBox) liveTranscriptBox.value = text;
    if (detectedLangText) detectedLangText.textContent = detectedLanguage || window.currentLanguage || "Tanglish";

    // Append to Chat stream
    addChatBubble(text, "user");

    // Call Agent NLU
    try {
      visualizerSubtext.textContent = "AI Co-Pilot analyzing entities...";
      const res = await window.API.agentHandle(text, "sess-driver-selvam");

      // Store current pending data
      currentPendingId = res.pending_id || "tx-" + Date.now();
      currentExtractedEntities = res.entities;

      // Update Confirmation Card
      if (chipIncomeVal) chipIncomeVal.textContent = "₹" + (res.entities.income || 0).toLocaleString("en-IN");
      if (chipExpenseVal) chipExpenseVal.textContent = "₹" + (res.entities.expense || 0).toLocaleString("en-IN");
      if (chipOwnerVal) chipOwnerVal.textContent = "₹" + (res.entities.owner_payment || 0).toLocaleString("en-IN");
      
      const netVal = (res.entities.income || 0) - (res.entities.expense || 0) - (res.entities.owner_payment || 0);
      if (chipNetVal) chipNetVal.textContent = "₹" + netVal.toLocaleString("en-IN");

      // Reveal Confirmation Card
      if (transactionConfirmContainer) {
        transactionConfirmContainer.classList.remove("hidden");
        transactionConfirmContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }

      // Add AI reply to chat stream
      if (res.reply_text) {
        addChatBubble(res.reply_text, "ai");
        if (ttsTextPreview) ttsTextPreview.textContent = `"${res.reply_text}"`;
        speakResponse(res.reply_text);
      }

      // Update Agent & AI trace module
      if (window.AgentModule && res.trace_steps) {
        window.AgentModule.updatePipelineTrace(res.trace_steps, res.entities);
      }

      visualizerSubtext.textContent = "Ready for driver confirmation.";

    } catch (err) {
      console.error("Agent handle error:", err);
      showVoiceAlert("Error in AI extraction: " + err.message, "danger");
      visualizerSubtext.textContent = "Microphone idle. Ready.";
    }
  }

  /**
   * Browser Speech Synthesis / Voice Playback Fallback
   */
  function speakResponse(text) {
    if (!('speechSynthesis' in window)) return;

    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.pitch = 1.0;
      // Prefer Tamil or Indian English voice if installed
      const voices = window.speechSynthesis.getVoices();
      const indicVoice = voices.find(v => v.lang.includes("ta") || v.lang.includes("en-IN"));
      if (indicVoice) utterance.voice = indicVoice;
      window.speechSynthesis.speak(utterance);
    } catch (e) {
      console.warn("TTS synthesis warning:", e);
    }
  }

  /**
   * Add message bubble to conversation stream
   */
  function addChatBubble(text, sender = "ai") {
    if (!chatStreamBox) return;

    const entry = document.createElement("div");
    entry.className = `chat-bubble-entry ${sender}`;
    const avatar = sender === "ai" ? "🤖" : "🛺";
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    entry.innerHTML = `
      <div class="bubble-avatar">${avatar}</div>
      <div class="bubble-body">
        <p>${escapeHtml(text)}</p>
        <span class="bubble-time">${now}</span>
      </div>
    `;

    chatStreamBox.appendChild(entry);
    chatStreamBox.scrollTop = chatStreamBox.scrollHeight;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Confirm or Reject Transaction
   */
  async function handleConfirmation(decision) {
    if (!currentPendingId) {
      if (window.showToast) window.showToast("No pending transaction to confirm.", "warning");
      return;
    }

    try {
      const res = await window.API.confirm(currentPendingId, decision);

      if (decision) {
        // Confirmed!
        if (window.showToast) {
          window.showToast(res.result || "Transaction confirmed and saved!", "success");
        }
        addChatBubble(`✓ Transaction approved! Logged Income ₹${currentExtractedEntities.income}, Expense ₹${currentExtractedEntities.expense}, Owner ₹${currentExtractedEntities.owner_payment}.`, "ai");

        // Cross-Module Notification: Update Finance & Settlement Ledgers
        if (window.FinanceModule && currentExtractedEntities) {
          window.FinanceModule.addTransaction({
            type: "income",
            description: "Voice Fare Collection",
            amount: currentExtractedEntities.income,
            mode: "Cash"
          });

          if (currentExtractedEntities.expense > 0) {
            window.FinanceModule.addTransaction({
              type: "expense",
              description: "Fuel / " + (currentExtractedEntities.category || "Expense"),
              amount: currentExtractedEntities.expense,
              mode: "Cash"
            });
          }

          if (currentExtractedEntities.owner_payment > 0) {
            window.FinanceModule.addTransaction({
              type: "owner",
              description: "Owner Bhatta payout",
              amount: currentExtractedEntities.owner_payment,
              mode: "UPI"
            });
          }
        }

        // Update Owner Settlement if applicable
        if (window.SettlementModule && currentExtractedEntities) {
          window.SettlementModule.recordDailySettlement(
            currentExtractedEntities.income,
            500, // standard expected
            currentExtractedEntities.owner_payment
          );
        }

      } else {
        // Cancelled
        if (window.showToast) {
          window.showToast("Transaction discarded.", "warning");
        }
        addChatBubble("✕ Transaction cancelled by driver. Nothing was logged.", "ai");
      }

      // Reset pending state & hide card
      currentPendingId = null;
      currentExtractedEntities = null;
      if (transactionConfirmContainer) {
        transactionConfirmContainer.classList.add("hidden");
      }

    } catch (err) {
      console.error("Confirmation error:", err);
      showVoiceAlert("Confirmation failed: " + err.message, "danger");
    }
  }

  /**
   * Initialize Module Listeners
   */
  function initVoiceModule() {
    // PTT Button Tap / Hold
    if (pttBtn) {
      pttBtn.addEventListener("click", () => {
        if (!isRecording) startRecording();
        else stopRecording();
      });
    }

    // Audio File Uploader
    if (audioFileInput) {
      audioFileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        if (audioFileNameDisplay) audioFileNameDisplay.textContent = file.name;
        showVoiceAlert(`Audio file "${file.name}" loaded. Processing transcription...`, "info");
        await processAudioInput(file);
      });
    }

    // Manual Text Submission
    if (submitManualVoiceBtn && manualVoiceInput) {
      const handleManual = () => {
        const val = manualVoiceInput.value.trim();
        if (val) {
          handleUserTextSubmission(val, window.currentLanguage);
          manualVoiceInput.value = "";
        }
      };

      submitManualVoiceBtn.addEventListener("click", handleManual);
      manualVoiceInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleManual();
        }
      });
    }

    // Editable transcript changes
    if (liveTranscriptBox) {
      liveTranscriptBox.addEventListener("change", () => {
        const edited = liveTranscriptBox.value.trim();
        if (edited) {
          handleUserTextSubmission(edited, window.currentLanguage);
        }
      });
    }

    // Confirm Buttons
    if (confirmYesBtn) confirmYesBtn.addEventListener("click", () => handleConfirmation(true));
    if (confirmNoBtn) confirmNoBtn.addEventListener("click", () => handleConfirmation(false));

    // Clear Chat
    if (clearChatHistoryBtn && chatStreamBox) {
      clearChatHistoryBtn.addEventListener("click", () => {
        chatStreamBox.innerHTML = `
          <div class="chat-bubble-entry ai">
            <div class="bubble-avatar">🤖</div>
            <div class="bubble-body">
              <p>Chat cleared. Speak or type anytime!</p>
              <span class="bubble-time">Now</span>
            </div>
          </div>
        `;
      });
    }

    // Sample Prompt Pills
    samplePills.forEach(pill => {
      pill.addEventListener("click", () => {
        const prompt = pill.getAttribute("data-prompt");
        if (prompt) {
          handleUserTextSubmission(prompt, window.currentLanguage);
        }
      });
    });

    drawIdleWaveform();
  }

  // Self-register
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initVoiceModule);
  } else {
    initVoiceModule();
  }

  // Export
  window.VoiceModule = {
    handleUserTextSubmission,
    startRecording,
    stopRecording
  };

})();

