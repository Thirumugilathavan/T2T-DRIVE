"""
Noise-Aware Retry & Clarification Policy for T2T DRIVE.
Generates concise, localized driver advisories in Tamil, Tanglish, and English
tailored to specific acoustic failure modes (silence, horn blasts, engine drone, low volume).
Enforces maximum retry bounds to prevent infinite repetition loops.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from app.voice.noise.speech_confidence import ConfidenceDirective
from app.voice.noise.noise_classifier import NoiseType


@dataclass
class RetryAdvisory:
    """Localized advice and retry disposition for the driver."""
    should_retry: bool
    retry_count: int
    max_retries: int
    reason_code: str
    display_message: str
    voice_prompt: str
    can_cancel: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NoiseRetryPolicy:
    """
    Provides short, driver-safe spoken and text advisories for mobile drivers.
    Does not overwhelm the driver with technical jargon; gives actionable real-world advice.
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def get_advisory(
        self,
        directive: ConfidenceDirective,
        noise_type: NoiseType,
        language: str = "tanglish",
        current_retry_count: int = 0,
        amount_hint: Optional[str] = None
    ) -> RetryAdvisory:
        """
        Determines whether to retry or fall back, generating localized prompts.
        """
        lang = language.lower() if language else "tanglish"
        if lang in ("ta", "ta-in", "tamil"):
            lang = "tamil"
        elif lang in ("en", "en-in", "english"):
            lang = "english"
        else:
            lang = "tanglish"
        next_count = current_retry_count + 1

        # Check if maximum retry limit exceeded
        if next_count > self.max_retries:
            return self._max_retries_exceeded_advisory(lang, next_count)

        # 1. Silence / No speech detected
        if directive == ConfidenceDirective.REJECT_UNUSABLE_AUDIO and noise_type == NoiseType.SILENCE:
            return self._build_silence_advisory(lang, next_count)

        # 2. Horn Blast during speech
        if noise_type == NoiseType.HONKING or directive == ConfidenceDirective.REQUEST_REPEAT and noise_type == NoiseType.HONKING:
            return self._build_honk_advisory(lang, next_count)

        # 3. Severe Engine / Traffic Noise
        if noise_type in (NoiseType.ENGINE_NOISE, NoiseType.TRAFFIC_NOISE, NoiseType.WIND_NOISE):
            return self._build_noise_advisory(lang, next_count)

        # 4. Low Volume / Muffled Speech
        if noise_type == NoiseType.LOW_VOLUME:
            return self._build_low_volume_advisory(lang, next_count)

        # 5. Clarification: Ambiguous Amount
        if directive == ConfidenceDirective.ASK_FOR_CLARIFICATION and amount_hint:
            return self._build_amount_clarification_advisory(lang, next_count, amount_hint)

        # 6. Clarification: Unclear Intent (Income vs Expense)
        if directive == ConfidenceDirective.ASK_FOR_CLARIFICATION:
            return self._build_intent_clarification_advisory(lang, next_count)

        # Generic repeat fallback
        return self._build_generic_repeat_advisory(lang, next_count)

    # ========================================================================
    # LOCALIZED PROMPT GENERATORS
    # ========================================================================

    def _build_silence_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "உங்கள் குரல் கேட்கவில்லை. மைக் அருகே வந்து மீண்டும் பேசவும்."
            voice = "உங்கள் குரல் கேட்கவில்லை. மீண்டும் சொல்லுங்கள்."
        elif lang == "english":
            disp = "No voice detected. Please speak closer to the microphone."
            voice = "No voice detected. Please speak again."
        else:  # tanglish
            disp = "Ungal voice kekkala. Mic kitta vandhu marubadi pesunga."
            voice = "Ungal voice kekkala. Marubadi sollunga."

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="SILENCE_DETECTED",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_honk_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "ஹாரன் சத்தம் அதிகம். சத்தம் குறைந்ததும் மீண்டும் கூறவும்."
            voice = "ஹாரன் சத்தம் அதிகம். மீண்டும் தெளிவாக சொல்லுங்கள்."
        elif lang == "english":
            disp = "Loud horn blast detected. Please repeat clearly."
            voice = "Loud horn detected. Please repeat clearly."
        else:  # tanglish
            disp = "Horn sound jasthi irundhudhu. Marubadi theliva sollunga."
            voice = "Horn sound jasthi. Marubadi sollunga."

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="HORN_INTERFERENCE",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_noise_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "வண்டி சத்தம் அதிகமாக உள்ளது. மைக் அருகில் வைத்து பேசவும்."
            voice = "சத்தம் அதிகமாக இருக்கிறது. கொஞ்சம் அருகில் பேசுங்கள்."
        elif lang == "english":
            disp = "Background noise is loud. Please speak closer to the microphone."
            voice = "Background noise is loud. Please speak closer to the mic."
        else:  # tanglish
            disp = "Vandi sound jasthi irukku. Konjam mic kitta pesunga."
            voice = "Sound jasthi irukku. Konjam mic kitta pesunga."

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="HEAVY_BACKGROUND_NOISE",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_low_volume_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "குரல் மிக மெதுவாக உள்ளது. சற்றே சத்தமாக பேசவும்."
            voice = "குரல் மிக மெதுவாக உள்ளது. சத்தமாக பேசுங்கள்."
        elif lang == "english":
            disp = "Voice volume was too low. Please speak slightly louder."
            voice = "Voice volume is low. Please speak louder."
        else:  # tanglish
            disp = "Voice romba low-aa irukku. Konjam satham-aa sollunga."
            voice = "Voice romba low-aa irukku. Konjam satham-aa sollunga."

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="LOW_VOLUME",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_amount_clarification_advisory(self, lang: str, count: int, amount: str) -> RetryAdvisory:
        if lang == "tamil":
            disp = f"தொகை சரியாக கேட்கவில்லை. தொகை ₹{amount} ரூபாயா?"
            voice = f"தொகை {amount} ரூபாயா?"
        elif lang == "english":
            disp = f"Amount unclear. Is the amount ₹{amount}?"
            voice = f"Is the amount {amount} rupees?"
        else:  # tanglish
            disp = f"Amount theliva kekkala. Amount ₹{amount} roobai-aa?"
            voice = f"Amount {amount} roobai-aa?"

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="UNCERTAIN_AMOUNT",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_intent_clarification_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "இது வருமானமா அல்லது செலவா என்று தெளிவாக கூறவும்."
            voice = "இது வருமானமா அல்லது செலவா?"
        elif lang == "english":
            disp = "Please clarify if this is income or an expense."
            voice = "Is this income or an expense?"
        else:  # tanglish
            disp = "Idhu income-aa illai expense-aa nu theliva sollunga."
            voice = "Idhu income-aa expense-aa?"

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="UNCLEAR_INTENT",
            display_message=disp,
            voice_prompt=voice
        )

    def _build_generic_repeat_advisory(self, lang: str, count: int) -> RetryAdvisory:
        if lang == "tamil":
            disp = "குரல் சரியாக கேட்கவில்லை. மீண்டும் கூறவும்."
            voice = "சரியாக கேட்கவில்லை. மீண்டும் சொல்லுங்கள்."
        elif lang == "english":
            disp = "Could not understand audio clearly. Please repeat."
            voice = "Could not understand clearly. Please repeat."
        else:  # tanglish
            disp = "Theliva kekkala. Marubadi sollunga."
            voice = "Theliva kekkala. Marubadi sollunga."

        return RetryAdvisory(
            should_retry=True,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="GENERIC_AUDIO_REPEAT",
            display_message=disp,
            voice_prompt=voice
        )

    def _max_retries_exceeded_advisory(self, lang: str, count: int) -> RetryAdvisory:
        """Fallback to manual UI action when voice recognition repeatedly struggles."""
        if lang == "tamil":
            disp = "தொடர்ந்து சத்தம் உள்ளது. திரையில் உள்ள பட்டனை பயன்படுத்தவும்."
            voice = "தொடர்ந்து சத்தம் உள்ளது. திரையில் உள்ள பட்டனை பயன்படுத்தவும்."
        elif lang == "english":
            disp = "Persistent background noise. Please tap the screen or use text input."
            voice = "Persistent noise detected. Please use on-screen buttons."
        else:  # tanglish
            disp = "Thodarndhu sound jasthi irukku. Screen-la irukura button use pannunga."
            voice = "Thodarndhu sound jasthi irukku. Screen-la irukura button use pannunga."

        return RetryAdvisory(
            should_retry=False,
            retry_count=count,
            max_retries=self.max_retries,
            reason_code="MAX_RETRIES_EXCEEDED",
            display_message=disp,
            voice_prompt=voice
        )
