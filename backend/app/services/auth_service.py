import secrets
import hashlib
import hmac
import datetime
import logging
from typing import Dict, Any, Optional
import jwt
from pymongo import ReturnDocument
from app.services.sms_service import get_sms_adapter
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

class AuthService:
    """Core Authentication & Security Service (Hardened)."""

    def __init__(self, db, config):
        self.db = db
        self.config = config
        self.sms_adapter = get_sms_adapter(config)

    def _hash_otp(self, phone: str, otp: str) -> str:
        """
        Computes standard HMAC-SHA-256 hash using the dedicated server-side OTP_HASH_SECRET.
        Reproducible, keyed cryptographic hashing preventing offline rainbow table attacks.
        """
        secret = self.config.get("OTP_HASH_SECRET", "dev-otp-hash-secret-t2t-drive-2026")
        if not secret:
            raise ValueError("Server configuration error: OTP_HASH_SECRET is missing.")
        message = f"{phone}:{otp}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def request_otp(self, phone: str) -> Dict[str, Any]:
        """
        Generates and delivers a secure OTP to the driver's phone with rate limiting.
        Enforces canonical E.164 phone normalization prior to query or storage.
        """
        canonical_phone = normalize_phone(phone)
        now = datetime.datetime.now(datetime.timezone.utc)
        window_start = now - datetime.timedelta(minutes=self.config.get("OTP_WINDOW_MINUTES", 10))

        # 1. Rate Limiting Check on Canonical Phone
        recent_requests = self.db.otp_verifications.count_documents({
            "phone": canonical_phone,
            "created_at": {"$gte": window_start}
        })

        max_limit = self.config.get("OTP_RATE_LIMIT_PER_WINDOW", 3)
        if recent_requests >= max_limit:
            logger.warning("OTP rate limit exceeded for phone: %s (%d requests in window)", canonical_phone, recent_requests)
            return {
                "success": False,
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many OTP requests. Please wait {self.config.get('OTP_WINDOW_MINUTES', 10)} minutes before trying again."
            }

        # 2. Cryptographic OTP Generation (6 digits)
        otp = f"{secrets.randbelow(900000) + 100000:06d}"
        otp_hash = self._hash_otp(canonical_phone, otp)
        expires_at = now + datetime.timedelta(minutes=self.config.get("OTP_EXPIRATION_MINUTES", 5))

        # 3. Store Hashed OTP (Never plaintext in database)
        self.db.otp_verifications.insert_one({
            "phone": canonical_phone,
            "otp_hash": otp_hash,
            "attempts": 0,
            "created_at": now,
            "expires_at": expires_at,
            "is_used": False
        })

        # 4. Dispatch via SMS Adapter
        delivery_res = self.sms_adapter.send_otp(canonical_phone, otp)

        response_payload = {
            "success": True,
            "phone": canonical_phone,
            "expires_in_seconds": self.config.get("OTP_EXPIRATION_MINUTES", 5) * 60,
            "mode": delivery_res.get("mode", "MOCK")
        }

        # In MOCK mode only, include demo OTP for developer and test convenience
        if delivery_res.get("mode") == "MOCK":
            response_payload["_mock_otp"] = otp

        return response_payload

    def verify_otp(self, phone: str, submitted_otp: str) -> Dict[str, Any]:
        """
        Atomically verifies the submitted OTP using Python's hmac.compare_digest.
        Separates state querying and attempt counting from hash comparison.
        Guarantees:
          - Constant-time secret comparison in Python via hmac.compare_digest (not inside MongoDB).
          - Atomic attempt incrementing without lost updates.
          - Atomic single-consumption (preventing concurrent double-use).
          - No increment of failed attempts on successful verification.
        """
        canonical_phone = normalize_phone(phone)
        now = datetime.datetime.now(datetime.timezone.utc)
        clean_otp = str(submitted_otp).strip()

        # Compute expected hash using HMAC-SHA-256 with OTP_HASH_SECRET
        expected_hash = self._hash_otp(canonical_phone, clean_otp)

        # 1. Retrieve the latest active OTP record for this phone
        record = self.db.otp_verifications.find_one(
            {"phone": canonical_phone, "is_used": False},
            sort=[("created_at", -1)]
        )

        if not record:
            return {"success": False, "error": "INVALID_OTP", "message": "No active OTP found. Please request a new OTP."}

        # 2. Check Expiration
        record_expires = record["expires_at"]
        if record_expires.tzinfo is None:
            record_expires = record_expires.replace(tzinfo=datetime.timezone.utc)

        if now > record_expires:
            return {"success": False, "error": "EXPIRED_OTP", "message": "OTP has expired. Please request a new one."}

        # 3. Check Attempt Limit Before Evaluation
        if record.get("attempts", 0) >= 3:
            return {"success": False, "error": "MAX_ATTEMPTS_EXCEEDED", "message": "Maximum OTP attempts exceeded. Please request a new OTP."}

        # 4. CONSTANT-TIME COMPARISON (Executed in Python via hmac.compare_digest)
        # The boolean result directly controls whether we proceed to atomic consumption or atomic failure.
        is_valid = hmac.compare_digest(record.get("otp_hash", ""), expected_hash)

        if is_valid:
            # 5. ATOMIC SUCCESS CONSUMPTION:
            # Atomically mark is_used = True ONLY IF still is_used == False and attempts < 3.
            # Guarantees that if two concurrent requests submit the correct OTP simultaneously,
            # only ONE will succeed, and the second will fail cleanly.
            consumed = self.db.otp_verifications.find_one_and_update(
                {
                    "_id": record["_id"],
                    "is_used": False,
                    "attempts": {"$lt": 3}
                },
                {
                    "$set": {"is_used": True, "used_at": now}
                },
                return_document=ReturnDocument.AFTER
            )

            if not consumed:
                # Concurrent request already consumed or locked out this OTP
                return {"success": False, "error": "INVALID_OTP", "message": "OTP has already been used or invalidated."}

            # Lookup or Auto-Register Driver Record
            driver = self.db.drivers.find_one({"phone": canonical_phone})
            if not driver:
                driver_count = self.db.drivers.count_documents({})
                driver_id = f"DRV_{1000 + driver_count + 1}"
                driver = {
                    "driver_id": driver_id,
                    "phone": canonical_phone,
                    "name": "Auto Driver",
                    "preferred_language": "tanglish",
                    "default_vehicle_id": None,
                    "status": "ACTIVE",
                    "created_at": now
                }
                self.db.drivers.insert_one(driver)
                logger.info("Auto-registered new driver: %s (%s)", driver_id, canonical_phone)

            # Issue Cryptographic JWT Access Token embedding unique jti
            token = self.generate_jwt_token(driver["driver_id"])

            return {
                "success": True,
                "token": token,
                "driver": {
                    "driver_id": driver["driver_id"],
                    "name": driver.get("name", "Auto Driver"),
                    "phone": driver["phone"],
                    "preferred_language": driver.get("preferred_language", "tanglish"),
                    "default_vehicle_id": driver.get("default_vehicle_id")
                }
            }

        else:
            # 6. ATOMIC FAILURE INCREMENT:
            # Atomically increment attempts by 1 in MongoDB.
            # Only increments if is_used is False and attempts < 3.
            failed_update = self.db.otp_verifications.find_one_and_update(
                {
                    "_id": record["_id"],
                    "is_used": False,
                    "attempts": {"$lt": 3}
                },
                {
                    "$inc": {"attempts": 1}
                },
                return_document=ReturnDocument.AFTER
            )

            if failed_update:
                new_attempts = failed_update.get("attempts", 0)
                if new_attempts >= 3:
                    # Invalidate record permanently
                    self.db.otp_verifications.update_one(
                        {"_id": record["_id"]},
                        {"$set": {"is_used": True, "invalidated_reason": "MAX_ATTEMPTS_EXCEEDED"}}
                    )
                    return {
                        "success": False,
                        "error": "MAX_ATTEMPTS_EXCEEDED",
                        "message": "Maximum OTP attempts reached. This OTP has been invalidated. Please request a new one."
                    }
                remaining = 3 - new_attempts
                return {
                    "success": False,
                    "error": "INVALID_OTP",
                    "message": f"Incorrect OTP entered. You have {remaining} attempt(s) remaining."
                }

            return {"success": False, "error": "MAX_ATTEMPTS_EXCEEDED", "message": "Maximum OTP attempts exceeded. Please request a new OTP."}

    def verify_pin(self, phone: str, pin: str) -> Dict[str, Any]:
        """
        Fallback authentication via 4-digit security PIN.
        """
        canonical_phone = normalize_phone(phone)
        driver = self.db.drivers.find_one({"phone": canonical_phone})

        if not driver:
            return {"success": False, "error": "NOT_FOUND", "message": "Driver account not found. Please login via OTP first."}

        stored_hash = driver.get("pin_hash")
        # In development demo, if no pin_hash set, allow '1234'
        if not stored_hash:
            env = self.config.get("ENV", "development").lower()
            if env == "production":
                return {"success": False, "error": "PIN_NOT_SET", "message": "PIN authentication is not configured for this account. Please log in via OTP."}
            if pin.strip() == "1234":
                token = self.generate_jwt_token(driver["driver_id"])
                return {"success": True, "token": token, "driver": driver}
            return {"success": False, "error": "INVALID_PIN", "message": "Invalid PIN entered."}

        # Verify hashed pin using sha256 or bcrypt with constant-time comparison
        salt = self.config.get("SECRET_KEY", "t2t-salt")
        test_hash = hashlib.sha256(f"{canonical_phone}:{pin}:{salt}".encode("utf-8")).hexdigest()
        if not hmac.compare_digest(stored_hash, test_hash):
            return {"success": False, "error": "INVALID_PIN", "message": "Invalid PIN entered."}

        token = self.generate_jwt_token(driver["driver_id"])
        return {"success": True, "token": token, "driver": driver}

    def generate_jwt_token(
        self,
        driver_id: str,
        session_id: Optional[str] = None,
        is_demo: bool = False,
        role: str = "DRIVER"
    ) -> str:
        """
        Issues a signed JWT access token embedding verified identity claims and a unique JTI token ID.
        """
        if not session_id:
            session_id = f"SESS_{secrets.token_hex(6)}"

        jti = f"JTI_{secrets.token_hex(16)}"
        now = datetime.datetime.now(datetime.timezone.utc)
        exp = now + datetime.timedelta(hours=self.config.get("JWT_ACCESS_EXPIRATION_HOURS", 24))

        payload = {
            "sub": driver_id,
            "session_id": session_id,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "is_demo": bool(is_demo),
            "role": str(role)
        }

        secret = self.config.get("JWT_SECRET", "dev-jwt-secret")
        algo = self.config.get("JWT_ALGORITHM", "HS256")
        return jwt.encode(payload, secret, algorithm=algo)

    def decode_jwt_token(self, token: str) -> Dict[str, Any]:
        """Validates and decodes JWT token; raises jwt.PyJWTError on invalid/expired tokens."""
        secret = self.config.get("JWT_SECRET", "dev-jwt-secret")
        algo = self.config.get("JWT_ALGORITHM", "HS256")
        return jwt.decode(token, secret, algorithms=[algo])

    def revoke_token(self, jti: str, session_id: str, driver_id: str, exp_timestamp: int) -> bool:
        """
        Persists server-side session revocation in MongoDB.
        Old revocation records auto-expire via MongoDB TTL matching the token's natural expiration.
        """
        if not jti:
            return False
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = datetime.datetime.fromtimestamp(exp_timestamp, datetime.timezone.utc)

        self.db.revoked_tokens.update_one(
            {"jti": jti},
            {"$set": {
                "jti": jti,
                "session_id": session_id,
                "driver_id": driver_id,
                "revoked_at": now,
                "expires_at": expires_at
            }},
            upsert=True
        )
        logger.info("Revoked JWT token %s for driver %s", jti, driver_id)
        return True

    def is_token_revoked(self, jti: str) -> bool:
        """Checks if a given JWT token JTI has been revoked on the server."""
        if not jti:
            return False
        record = self.db.revoked_tokens.find_one({"jti": jti})
        return bool(record)
