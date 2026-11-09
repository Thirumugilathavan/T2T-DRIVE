"""
Multi-Dimensional Speech & Intent Confidence Evaluator for T2T DRIVE.
Assesses audio quality, STT reliability, language certainty, intent confidence, and slot integrity.
Produces actionable decision directives:
- ACCEPT_FOR_INTERPRETATION
- REQUIRE_EXPLICIT_CONFIRMATION
- ASK_FOR_CLARIFICATION
- REQUEST_REPEAT
- REJECT_UNUSABLE_AUDIO
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from app.voice.noise.snr_estimator import SNREstimate, SNRQuality
from app.voice.noise.noise_classifier import NoiseClassification, NoiseType
from app.voice.noise.vad import VADResult


class ConfidenceDirective(str, Enum):
    """Action directive produced by confidence decision policy."""
    ACCEPT_FOR_INTERPRETATION = "ACCEPT_FOR_INTERPRETATION"
    REQUIRE_EXPLICIT_CONFIRMATION = "REQUIRE_EXPLICIT_CONFIRMATION"
    ASK_FOR_CLARIFICATION = "ASK_FOR_CLARIFICATION"
    REQUEST_REPEAT = "REQUEST_REPEAT"
    REJECT_UNUSABLE_AUDIO = "REJECT_UNUSABLE_AUDIO"


@dataclass
class MultiDimensionalConfidence:
    """Explicit multi-dimensional confidence breakdown."""
    acoustic_confidence: float
    stt_confidence: Optional[float]
    language_confidence: float
    intent_confidence: float
    slot_confidence: float
    directive: ConfidenceDirective
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["directive"] = self.directive.value
        return d


class SpeechConfidenceEvaluator:
    """
    Evaluates acoustic, linguistic, and financial certainty.
    Enforces the fundamental safety invariant: good audio does not equal correct intent,
    and no financial mutation may bypass explicit confirmation.
    """

    def __init__(
        self,
        min_acceptable_snr_db: float = 3.5,
        min_intent_confidence: float = 0.65,
        min_acoustic_confidence: float = 0.40
    ):
        self.min_acceptable_snr_db = min_acceptable_snr_db
        self.min_intent_confidence = min_intent_confidence
        self.min_acoustic_confidence = min_acoustic_confidence

    def evaluate(
        self,
        noise_class: NoiseClassification,
        snr_est: SNREstimate,
        vad_res: VADResult,
        intent: Optional[str] = None,
        intent_confidence: float = 0.80,
        slots: Optional[Dict[str, Any]] = None,
        missing_slots: Optional[List[str]] = None,
        stt_confidence: Optional[float] = None,
        language_confidence: float = 0.90
    ) -> MultiDimensionalConfidence:
        """
        Synthesizes multi-dimensional confidence scores into an unambiguous operational directive.
        """
        reasons: List[str] = []
        slots = slots or {}
        missing_slots = missing_slots or []

        # 1. Compute Acoustic Confidence
        acoustic_conf = self._calculate_acoustic_confidence(noise_class, snr_est, vad_res, reasons)

        # 2. Compute Slot Confidence
        slot_conf = self._calculate_slot_confidence(intent, slots, missing_slots, reasons)

        # 3. Decision Matrix
        directive = ConfidenceDirective.ACCEPT_FOR_INTERPRETATION

        # Rule A: Unusable audio (Silence or No Speech or Severe Clipping)
        if noise_class.primary_category == NoiseType.SILENCE or not vad_res.has_speech:
            directive = ConfidenceDirective.REJECT_UNUSABLE_AUDIO
            reasons.append("Audio contains no detectable speech.")
        elif noise_class.primary_category == NoiseType.CLIPPING and noise_class.supporting_metrics.get("clipping_pct", 0) > 8.0:
            directive = ConfidenceDirective.REJECT_UNUSABLE_AUDIO
            reasons.append("Audio waveform is severely clipped and distorted.")

        # Rule B: High noise interference requiring speech repeat
        elif (
            (snr_est.quality == SNRQuality.VERY_POOR and snr_est.snr_db is not None and snr_est.snr_db < self.min_acceptable_snr_db) or
            noise_class.primary_category == NoiseType.HONKING or
            acoustic_conf < self.min_acoustic_confidence
        ):
            directive = ConfidenceDirective.REQUEST_REPEAT
            if noise_class.primary_category == NoiseType.HONKING:
                reasons.append("Loud vehicle horn blast coincided with driver speech.")
            else:
                reasons.append("Acoustic noise floor is too high for reliable recognition.")

        # Rule C: Ambiguous entity or missing mandatory slot requiring clarification
        elif len(missing_slots) > 0 or slot_conf < 0.60:
            directive = ConfidenceDirective.ASK_FOR_CLARIFICATION
            reasons.append(f"Missing required parameter(s): {', '.join(missing_slots)}")

        # Rule D: Financial writes or query requiring explicit confirmation
        elif intent in ("RECORD_EXPENSE", "RECORD_INCOME", "CALCULATE_SETTLEMENT", "ADD_MAINTENANCE", "PAY_CHALLAN"):
            # All financial writes MUST pass through confirmation firewall
            directive = ConfidenceDirective.REQUIRE_EXPLICIT_CONFIRMATION
            reasons.append("Financial transaction proposal requires driver verification.")

        # Rule E: Marginal acoustic quality with non-financial query
        elif acoustic_conf < 0.70 or (stt_confidence is not None and stt_confidence < 0.70):
            directive = ConfidenceDirective.REQUIRE_EXPLICIT_CONFIRMATION
            reasons.append("Moderate background noise; confirming intent to prevent misaction.")

        else:
            directive = ConfidenceDirective.ACCEPT_FOR_INTERPRETATION

        return MultiDimensionalConfidence(
            acoustic_confidence=round(acoustic_conf, 2),
            stt_confidence=round(stt_confidence, 2) if stt_confidence is not None else None,
            language_confidence=round(language_confidence, 2),
            intent_confidence=round(intent_confidence, 2),
            slot_confidence=round(slot_conf, 2),
            directive=directive,
            reasons=reasons
        )

    # ========================================================================
    # INTERNAL HELPERS
    # ========================================================================

    def _calculate_acoustic_confidence(
        self,
        noise_class: NoiseClassification,
        snr_est: SNREstimate,
        vad_res: VADResult,
        reasons: List[str]
    ) -> float:
        """Computes composite acoustic quality score in range [0.0, 1.0]."""
        if noise_class.primary_category == NoiseType.SILENCE:
            return 0.05
        if not vad_res.has_speech:
            return 0.10

        score = 0.85

        # SNR adjustments
        if snr_est.snr_db is not None:
            if snr_est.snr_db >= 18.0:
                score += 0.10
            elif snr_est.snr_db >= 12.0:
                score += 0.02
            elif snr_est.snr_db >= 7.0:
                score -= 0.15
            else:
                score -= 0.35
        else:
            score -= 0.10

        # Noise category penalties
        if noise_class.primary_category == NoiseType.HONKING:
            score -= 0.35
        elif noise_class.primary_category == NoiseType.ENGINE_NOISE:
            score -= 0.15
        elif noise_class.primary_category == NoiseType.TRAFFIC_NOISE:
            score -= 0.20
        elif noise_class.primary_category == NoiseType.WIND_NOISE:
            score -= 0.25
        elif noise_class.primary_category == NoiseType.LOW_VOLUME:
            score -= 0.20
        elif noise_class.primary_category == NoiseType.CLIPPING:
            score -= 0.30

        # VAD speech ratio
        if vad_res.speech_percentage < 15.0:
            score -= 0.15

        return max(0.05, min(0.99, score))

    def _calculate_slot_confidence(
        self,
        intent: Optional[str],
        slots: Dict[str, Any],
        missing_slots: List[str],
        reasons: List[str]
    ) -> float:
        """Evaluates whether all mandatory entities for the intent are present and plausible."""
        if not intent:
            return 0.50

        if intent in ("RECORD_EXPENSE", "RECORD_INCOME", "ADD_MAINTENANCE"):
            has_amount = "amount" in slots and slots["amount"] is not None
            has_category = "category" in slots and slots["category"] is not None

            if has_amount and has_category:
                return 0.95
            elif has_amount:
                return 0.80
            elif has_category:
                return 0.55
            else:
                return 0.30

        # Other intents (HELP, SUMMARY, EXPIRY, CHALLANS)
        return 0.90 if len(missing_slots) == 0 else 0.60
