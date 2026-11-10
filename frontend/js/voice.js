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
  const ttsStatusPill = document.getElementById("ttsStatusPill");
  const chatStreamBox = document.getElementById("chatStreamBox");
  const clearChatHistoryBtn = document.getElementById("clearChatHistoryBtn");
  const samplePills = document.querySelectorAll(".sample-pill");
  const voiceAlertBox = document.getElementById("voiceAlertBox");

  // State Variables
  let mediaRecorder = null;
  let audioChunks = [];
  let isRecording = false;
  let isProcessingAudio = false;
  let recordTimerInterval = null;
  let recordStartTime = 0;
  let audioContext = null;
  let analyser = null;
  let animationFrameId = null;
  let currentPendingId = null;
  let currentExtractedEntities = null;
  let currentSessionId = null;
  let currentTtsBlobUrl = null;

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
   * Convert Base64 audio string into an Object URL Blob for native audio playback
   */
  function base64ToBlobUrl(base64Data, contentType = "audio/wav") {
    const cleaned = (base64Data || "").replace(/^data:audio\/\w+;base64,/, "").trim();
    const byteCharacters = atob(cleaned);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: contentType });
    return URL.createObjectURL(blob);
  }

  /**
   * Play Audio generated by Gnani Timbre TTS via <audio id="ttsAudioPlayer">
   */
  function playTtsAudio(base64Data, provider = "Gnani Timbre") {
    if (!base64Data || !ttsAudioPlayer) return;

    if (currentTtsBlobUrl) {
      try {
        URL.revokeObjectURL(currentTtsBlobUrl);
      } catch (e) {}
      currentTtsBlobUrl = null;
    }

    try {
      currentTtsBlobUrl = base64ToBlobUrl(base64Data, "audio/wav");
      ttsAudioPlayer.src = currentTtsBlobUrl;
      ttsAudioPlayer.load();

      if (ttsStatusPill) {
        const provStr = String(provider || "").toLowerCase();
        const isLive = provStr.includes("gnani") && !provStr.includes("mock");
        if (isLive) {
          ttsStatusPill.textContent = "LIVE";
          ttsStatusPill.className = "pill pill-live";
        } else {
          ttsStatusPill.textContent = "SIMULATED";
          ttsStatusPill.className = "pill pill-mock";
        }
      }

      const playPromise = ttsAudioPlayer.play();
      if (playPromise !== undefined) {
        playPromise.catch((err) => {
          console.warn("Autoplay was prevented by browser policy:", err);
          showVoiceAlert("Voice reply ready. Tap Play on the audio player to listen.", "info");
        });
      }
    } catch (err) {
      console.error("Failed to load and play TTS audio:", err);
      showVoiceAlert("Error loading synthesized audio: " + err.message, "warning");
    }
  }

  /**
   * Browser Speech Synthesis (Explicit Fallback Only)
   */
  function speakBrowserFallback(text) {
    if (!('speechSynthesis' in window)) return;
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.pitch = 1.0;
      const voices = window.speechSynthesis.getVoices();
      const indicVoice = voices.find(v => v.lang.includes("ta") || v.lang.includes("en-IN"));
      if (indicVoice) utterance.voice = indicVoice;
      window.speechSynthesis.speak(utterance);
      if (ttsStatusPill) {
        ttsStatusPill.textContent = "SIMULATED";
        ttsStatusPill.className = "pill pill-mock";
      }
    } catch (e) {
      console.warn("Browser speech fallback warning:", e);
    }
  }

  /**
   * Process Audio Input via Unified Voice Turn (/api/voice/chat)
   */
  async function processAudioInput(blob) {
    if (isProcessingAudio) {
      console.warn("Audio processing already in progress. Ignoring duplicate submission.");
      return;
    }
    isProcessingAudio = true;

    try {
      if (pttBtn) pttBtn.disabled = true;
      if (pttLabel) pttLabel.textContent = "Processing...";
      if (visualizerSubtext) visualizerSubtext.textContent = "Processing speech with Gnani AI co-pilot...";
      const lang = window.currentLanguage || "tanglish";

      // Direct call to unified endpoint /api/voice/chat
      const res = await window.API.voiceChat(blob, lang, currentSessionId, true);

      drawIdleWaveform();

      if (!res) {
        throw new Error("No response received from voice service.");
      }

      // 1. Noise Intelligence & Acoustic Telemetry Display
      const quality = res.audio_quality || "UNKNOWN";
      const noiseType = res.noise_type || (res.noise_classification ? res.noise_classification.primary_category : "NORMAL");
      const snrVal = (res.snr_db !== undefined && res.snr_db !== null)
        ? res.snr_db
        : (res.snr_estimate ? res.snr_estimate.snr_db : null);
      const snrText = (snrVal !== undefined && snrVal !== null) ? ` • SNR: ${Number(snrVal).toFixed(1)}dB` : "";
      const prep = (res.preprocessing_applied && res.preprocessing_applied.length > 0)
        ? ` [Filtered: ${res.preprocessing_applied.join(", ")}]`
        : "";

      let qualityColor = "#22c55e"; // green
      if (quality === "MODERATE") qualityColor = "#eab308";
      else if (quality === "POOR" || quality === "VERY_POOR") qualityColor = "#f97316";
      else if (quality === "UNUSABLE") qualityColor = "#ef4444";

      if (visualizerSubtext) {
        visualizerSubtext.innerHTML = `Audio Quality: <b style="color:${qualityColor}">${quality}</b> (${noiseType}${snrText})${prep}`;
      }

      if (res.retry_advisory && res.retry_advisory.display_message) {
        showVoiceAlert(res.retry_advisory.display_message, res.retry_advisory.should_retry ? "warning" : "danger");
      }

      // 2. Display Recognized Transcript in UI & Chat Box
      const transcript = (res.transcript || res.text || "").trim();
      const detectedLang = res.detected_language || lang;

      if (transcript) {
        if (liveTranscriptBox) liveTranscriptBox.value = transcript;
        if (detectedLangText) detectedLangText.textContent = detectedLang;
        addChatBubble(transcript, "user");
      } else if (res.error) {
        showVoiceAlert(res.error, "warning");
        if (visualizerSubtext) visualizerSubtext.textContent = res.error;
        return;
      }

      // 3. Track Conversation Session
      if (res.session_id) {
        currentSessionId = res.session_id;
      }

      // 4. Extract Entities and Update Confirmation Firewall Card
      let entities = res.entities;
      const activePending = res.active_pending_action;

      if (!entities && activePending && activePending.proposed_data) {
        const pData = activePending.proposed_data;
        if (pData.transactions && Array.isArray(pData.transactions)) {
          let inc = 0, exp = 0, own = 0;
          pData.transactions.forEach(t => {
            const tAmt = parseFloat(t.amount || 0) || 0;
            const tCat = (t.category || "").toUpperCase();
            const tType = (t.action_type || t.transaction_type || "").toUpperCase();
            if (tType.includes("INCOME") || tCat.includes("FARE") || tCat.includes("COLLECTION")) {
              inc += tAmt;
            } else if (tType.includes("OWNER") || tCat.includes("OWNER")) {
              own += tAmt;
            } else {
              exp += tAmt;
            }
          });
          entities = {
            income: inc,
            expense: exp,
            owner_payment: own,
            amount: inc + exp + own,
            category: "BATCH"
          };
        } else {
          const amt = parseFloat(pData.amount || 0) || 0;
          const aType = activePending.action_type || "";
          entities = {
            income: aType.includes("INCOME") ? amt : 0,
            expense: aType.includes("EXPENSE") ? amt : 0,
            owner_payment: aType.includes("OWNER") ? amt : 0,
            amount: amt,
            category: pData.category || "OTHER"
          };
        }
      } else if (!entities && res.slots) {
        const amt = parseFloat(res.slots.amount || 0) || 0;
        const intent = res.intent || "";
        entities = {
          income: intent.includes("INCOME") ? amt : 0,
          expense: intent.includes("EXPENSE") ? amt : 0,
          owner_payment: intent.includes("OWNER") ? amt : 0,
          amount: amt,
          category: res.slots.category || "OTHER"
        };
      }

      const pendingId = res.pending_id || (activePending ? activePending.pending_action_id : null);

      if (pendingId && entities) {
        currentPendingId = pendingId;
        currentExtractedEntities = entities;

        if (chipIncomeVal) chipIncomeVal.textContent = "₹" + (entities.income || 0).toLocaleString("en-IN");
        if (chipExpenseVal) chipExpenseVal.textContent = "₹" + (entities.expense || 0).toLocaleString("en-IN");
        if (chipOwnerVal) chipOwnerVal.textContent = "₹" + (entities.owner_payment || 0).toLocaleString("en-IN");

        const netVal = (entities.income || 0) - (entities.expense || 0) - (entities.owner_payment || 0);
        if (chipNetVal) chipNetVal.textContent = "₹" + netVal.toLocaleString("en-IN");

        if (transactionConfirmContainer) {
          transactionConfirmContainer.classList.remove("hidden");
          transactionConfirmContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else {
        currentPendingId = null;
        currentExtractedEntities = null;
        if (transactionConfirmContainer) {
          transactionConfirmContainer.classList.add("hidden");
        }
      }

      // 5. Display Assistant's Response in Chat Stream (Safe Fallbacks)
      const assistantText = res.agent_message || res.reply_text || res.message || res.agent_voice_text || "";
      if (assistantText) {
        addChatBubble(assistantText, "ai");
        if (ttsTextPreview) ttsTextPreview.textContent = `"${assistantText}"`;
      }

      // 6. Play Gnani Timbre Synthesized Audio
      if (res.tts_audio_base64 && res.tts_status !== "ERROR") {
        playTtsAudio(res.tts_audio_base64, res.tts_provider || "mock_timbre");
      } else if (res.tts_status === "ERROR") {
        console.warn("TTS generation failed or unavailable:", res.error);
        if (ttsStatusPill) {
          ttsStatusPill.textContent = "ERROR";
          ttsStatusPill.className = "pill pill-error";
        }
        showVoiceAlert("Voice synthesis unavailable. Showing text response.", "info");
      } else {
        if (ttsStatusPill) {
          ttsStatusPill.textContent = "IDLE";
          ttsStatusPill.className = "pill pill-idle";
        }
      }

      // 7. Update Agent Pipeline Telemetry
      if (window.AgentModule && res.trace_steps) {
        window.AgentModule.updatePipelineTrace(res.trace_steps, entities);
      }

    } catch (err) {
      console.error("Voice turn processing error:", err);
      if (visualizerSubtext) visualizerSubtext.textContent = "Voice processing error: " + err.message;
      showVoiceAlert("Voice processing failed: " + err.message, "danger");
      drawIdleWaveform();
    } finally {
      isProcessingAudio = false;
      if (pttBtn) {
        pttBtn.disabled = false;
        pttBtn.classList.remove("recording");
      }
      if (pttLabel) pttLabel.textContent = "Tap & Speak";
    }
  }

  /**
   * Process Natural Language Prompt (from manual text submission)
   */
  async function handleUserTextSubmission(text, detectedLanguage = null) {
    if (!text || !text.trim()) return;
    if (isProcessingAudio) return;
    isProcessingAudio = true;

    // Put into transcript box
    if (liveTranscriptBox) liveTranscriptBox.value = text;
    if (detectedLangText) detectedLangText.textContent = detectedLanguage || window.currentLanguage || "Tanglish";

    // Append to Chat stream
    addChatBubble(text, "user");

    // Call Agent NLU
    try {
      if (visualizerSubtext) visualizerSubtext.textContent = "AI Co-Pilot analyzing entities...";
      const res = await window.API.agentHandle(text, currentSessionId || "sess-driver-selvam");

      if (res.session_id) currentSessionId = res.session_id;

      // Extract entities
      let entities = res.entities;
      const activePending = res.active_pending_action;
      if (!entities && activePending && activePending.proposed_data) {
        const pData = activePending.proposed_data;
        if (pData.transactions && Array.isArray(pData.transactions)) {
          let inc = 0, exp = 0, own = 0;
          pData.transactions.forEach(t => {
            const tAmt = parseFloat(t.amount || 0) || 0;
            const tCat = (t.category || "").toUpperCase();
            const tType = (t.action_type || t.transaction_type || "").toUpperCase();
            if (tType.includes("INCOME") || tCat.includes("FARE") || tCat.includes("COLLECTION")) {
              inc += tAmt;
            } else if (tType.includes("OWNER") || tCat.includes("OWNER")) {
              own += tAmt;
            } else {
              exp += tAmt;
            }
          });
          entities = {
            income: inc,
            expense: exp,
            owner_payment: own,
            amount: inc + exp + own,
            category: "BATCH"
          };
        } else {
          const amt = parseFloat(pData.amount || 0) || 0;
          const aType = activePending.action_type || "";
          entities = {
            income: aType.includes("INCOME") ? amt : 0,
            expense: aType.includes("EXPENSE") ? amt : 0,
            owner_payment: aType.includes("OWNER") ? amt : 0,
            amount: amt,
            category: pData.category || "OTHER"
          };
        }
      } else if (!entities && res.slots) {
        const amt = parseFloat(res.slots.amount || 0) || 0;
        const intent = res.intent || "";
        entities = {
          income: intent.includes("INCOME") ? amt : 0,
          expense: intent.includes("EXPENSE") ? amt : 0,
          owner_payment: intent.includes("OWNER") ? amt : 0,
          amount: amt,
          category: res.slots.category || "OTHER"
        };
      }

      const pendingId = res.pending_id || (activePending ? activePending.pending_action_id : null);
      if (pendingId && entities) {
        currentPendingId = pendingId;
        currentExtractedEntities = entities;

        if (chipIncomeVal) chipIncomeVal.textContent = "₹" + (entities.income || 0).toLocaleString("en-IN");
        if (chipExpenseVal) chipExpenseVal.textContent = "₹" + (entities.expense || 0).toLocaleString("en-IN");
        if (chipOwnerVal) chipOwnerVal.textContent = "₹" + (entities.owner_payment || 0).toLocaleString("en-IN");

        const netVal = (entities.income || 0) - (entities.expense || 0) - (entities.owner_payment || 0);
        if (chipNetVal) chipNetVal.textContent = "₹" + netVal.toLocaleString("en-IN");

        if (transactionConfirmContainer) {
          transactionConfirmContainer.classList.remove("hidden");
          transactionConfirmContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }

      // Add AI reply to chat stream
      const assistantText = res.agent_message || res.reply_text || res.message || res.voice_text || "";
      if (assistantText) {
        addChatBubble(assistantText, "ai");
        if (ttsTextPreview) ttsTextPreview.textContent = `"${assistantText}"`;

        // Request speech synthesis from backend Timbre TTS
        try {
          const ttsRes = await window.API.speak(res.voice_text || assistantText, detectedLanguage || "ta");
          if (ttsRes && ttsRes.audio_base64) {
            playTtsAudio(ttsRes.audio_base64, ttsRes.provider || "Gnani Timbre");
          } else {
            speakBrowserFallback(assistantText);
          }
        } catch (ttsErr) {
          console.warn("TTS synthesis error:", ttsErr);
          speakBrowserFallback(assistantText);
        }
      }

      // Update Agent & AI trace module
      if (window.AgentModule && res.trace_steps) {
        window.AgentModule.updatePipelineTrace(res.trace_steps, entities);
      }

      if (visualizerSubtext) visualizerSubtext.textContent = "Ready for driver confirmation.";

    } catch (err) {
      console.error("Agent handle error:", err);
      showVoiceAlert("Error in AI extraction: " + err.message, "danger");
      if (visualizerSubtext) visualizerSubtext.textContent = "Microphone idle. Ready.";
    } finally {
      isProcessingAudio = false;
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
    stopRecording,
    processAudioInput
  };

})();

