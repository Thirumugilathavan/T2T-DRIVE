import abc
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class BaseSMSAdapter(abc.ABC):
    """Abstract Base Class for SMS delivery adapters."""

    @abc.abstractmethod
    def send_otp(self, phone: str, otp: str) -> Dict[str, Any]:
        """
        Sends an OTP message to the driver's phone.
        Returns a dict with {"success": bool, "message_id": str, "mode": str}
        """
        pass


class MockSMSAdapter(BaseSMSAdapter):
    """
    Clearly labelled Mock SMS adapter for local development, hackathon demos, and automated testing.
    Logs the OTP to debug logs and returns delivery success without incurring SMS gateway charges.
    """

    def send_otp(self, phone: str, otp: str) -> Dict[str, Any]:
        logger.info("[MOCK SMS] Outgoing OTP for %s: %s (Mode: MOCK, Cost: ₹0.00)", phone, otp)
        return {
            "success": True,
            "message_id": f"mock-msg-{phone[-4:]}-{otp}",
            "mode": "MOCK",
            "info": "Mock SMS delivery simulated successfully."
        }


class Fast2SMSAdapter(BaseSMSAdapter):
    """
    Live Indian SMS gateway adapter for production delivery to auto/cab drivers.
    Configured via SMS_API_KEY environment variable.
    """

    def __init__(self, api_key: str, sender_id: str = "T2TDRV"):
        self.api_key = api_key
        self.sender_id = sender_id

    def send_otp(self, phone: str, otp: str) -> Dict[str, Any]:
        if not self.api_key:
            logger.warning("No SMS_API_KEY provided for Fast2SMS. Falling back to mock behavior.")
            return MockSMSAdapter().send_otp(phone, otp)

        import httpx
        clean_phone = phone.replace("+91", "").strip()
        url = "https://www.fast2sms.com/dev/bulkV2"
        headers = {"authorization": self.api_key}
        payload = {
            "variables_values": otp,
            "route": "otp",
            "numbers": clean_phone,
        }

        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(url, headers=headers, data=payload)
                data = res.json()
                is_success = data.get("return", False)
                return {
                    "success": is_success,
                    "message_id": data.get("request_id", ""),
                    "mode": "LIVE",
                    "info": data.get("message", [""])[0] if isinstance(data.get("message"), list) else str(data.get("message"))
                }
        except Exception as err:
            logger.error("Fast2SMS gateway delivery failed: %s", err)
            return {
                "success": False,
                "message_id": "",
                "mode": "LIVE_ERROR",
                "error": str(err)
            }


def get_sms_adapter(config) -> BaseSMSAdapter:
    """Factory creating the appropriate SMS adapter based on configuration."""
    mode = config.get("SMS_PROVIDER_MODE", "mock").lower()
    if mode == "live":
        api_key = config.get("SMS_API_KEY", "")
        sender_id = config.get("SMS_SENDER_ID", "T2TDRV")
        return Fast2SMSAdapter(api_key=api_key, sender_id=sender_id)
    return MockSMSAdapter()
