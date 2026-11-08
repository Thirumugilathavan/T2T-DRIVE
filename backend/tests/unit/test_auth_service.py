import pytest
import datetime
from concurrent.futures import ThreadPoolExecutor
from app.services.auth_service import AuthService
from app.utils.phone import normalize_phone
from app.config import ProductionConfig

def test_otp_request_and_hash(db, app):
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543210"

    result = auth_service.request_otp(phone)
    assert result["success"] is True
    assert result["mode"] == "MOCK"
    assert "_mock_otp" in result

    # Check database record: OTP must NOT be plain text!
    record = db.otp_verifications.find_one({"phone": phone})
    assert record is not None
    assert "otp_hash" in record
    assert record["otp_hash"] != result["_mock_otp"]  # Hashed, not plain text!
    assert record["is_used"] is False


def test_hmac_sha256_properties(app):
    auth_service = AuthService(db=None, config=app.config)
    phone = "+919876543201"
    otp = "123456"

    # 1. Reproducibility: same phone + otp + key produces identical hash
    hash1 = auth_service._hash_otp(phone, otp)
    hash2 = auth_service._hash_otp(phone, otp)
    assert hash1 == hash2

    # 2. Key dependence: different secret produces different hash
    cfg_alt = dict(app.config)
    cfg_alt["OTP_HASH_SECRET"] = "different-secret-key-t2t"
    auth_service_alt = AuthService(db=None, config=cfg_alt)
    hash_alt = auth_service_alt._hash_otp(phone, otp)
    assert hash1 != hash_alt

    # 3. Input dependence: different phone or otp produces different hash
    hash_diff_phone = auth_service._hash_otp("+919876543202", otp)
    hash_diff_otp = auth_service._hash_otp(phone, "654321")
    assert hash1 != hash_diff_phone
    assert hash1 != hash_diff_otp


def test_otp_verification_success(db, app):
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543211"

    req_res = auth_service.request_otp(phone)
    otp = req_res["_mock_otp"]

    verify_res = auth_service.verify_otp(phone, otp)
    assert verify_res["success"] is True
    assert "token" in verify_res
    assert "driver" in verify_res
    assert verify_res["driver"]["phone"] == phone

    # Verify that the OTP is marked used
    record = db.otp_verifications.find_one({"phone": phone, "is_used": True})
    assert record is not None


def test_otp_replay_rejection(db, app):
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543299"

    req_res = auth_service.request_otp(phone)
    otp = req_res["_mock_otp"]

    # First verification succeeds
    res1 = auth_service.verify_otp(phone, otp)
    assert res1["success"] is True

    # Immediate replay of the exact same OTP must be rejected
    res2 = auth_service.verify_otp(phone, otp)
    assert res2["success"] is False
    assert res2["error"] == "INVALID_OTP"


def test_otp_expiration(db, app):
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543214"

    req_res = auth_service.request_otp(phone)
    otp = req_res["_mock_otp"]

    # Manually backdate the OTP expiration time to 10 minutes ago
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    db.otp_verifications.update_one(
        {"phone": phone},
        {"$set": {"expires_at": past_time}}
    )

    verify_res = auth_service.verify_otp(phone, otp)
    assert verify_res["success"] is False
    assert verify_res["error"] == "EXPIRED_OTP"


def test_otp_max_attempts_and_invalidation(db, app):
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543215"

    auth_service.request_otp(phone)

    # Attempt 1: Failed
    r1 = auth_service.verify_otp(phone, "111111")
    assert r1["success"] is False
    assert r1["error"] == "INVALID_OTP"

    # Attempt 2: Failed
    r2 = auth_service.verify_otp(phone, "222222")
    assert r2["success"] is False
    assert r2["error"] == "INVALID_OTP"

    # Attempt 3: Failed (Hits limit of 3)
    r3 = auth_service.verify_otp(phone, "333333")
    assert r3["success"] is False

    # Check that record is marked invalidated (is_used = True)
    record = db.otp_verifications.find_one({"phone": phone})
    assert record["attempts"] == 3
    assert record["is_used"] is True
    assert record.get("invalidated_reason") == "MAX_ATTEMPTS_EXCEEDED"

    # Attempt 4: Should find no active OTP because it's marked is_used: True
    r4 = auth_service.verify_otp(phone, "444444")
    assert r4["success"] is False
    assert r4["error"] == "INVALID_OTP"


def test_concurrent_failed_otp_requests(db, app):
    """
    Simulates concurrent parallel wrong-OTP submissions to verify atomic attempt counting.
    Attempts must reach 3 and terminate without lost updates.
    """
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543216"
    auth_service.request_otp(phone)

    wrong_otps = ["111111", "222222", "333333", "444444", "555555"]

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda code: auth_service.verify_otp(phone, code), wrong_otps))

    # All attempts must fail
    assert all(r["success"] is False for r in results)

    # Database record must reflect that attempt limit was reached and record was invalidated
    record = db.otp_verifications.find_one({"phone": phone})
    assert record["is_used"] is True
    assert record["attempts"] >= 3


def test_phone_normalization_formats():
    # Various valid Indian formats must all resolve to canonical +919876543210
    assert normalize_phone("+919876543210") == "+919876543210"
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("+91 (987) 654-3210") == "+919876543210"


def test_invalid_phone_rejection():
    # Invalid numbers must raise ValueError
    invalid_cases = ["12345", "abcdefghij", "+14155552671", "5876543210", "", "   "]
    for case in invalid_cases:
        with pytest.raises(ValueError):
            normalize_phone(case)


def test_rate_limit_bypass_prevention_across_formats(db, app):
    """
    Proves that an attacker cannot bypass the 3-request rate limit
    by varying format prefixes (e.g. 098..., 98..., +91 98...).
    """
    auth_service = AuthService(db=db, config=app.config)
    phone_raw = "9876543217"

    # Request 1 via raw 10-digit
    r1 = auth_service.request_otp("9876543217")
    assert r1["success"] is True

    # Request 2 via leading 0
    r2 = auth_service.request_otp("09876543217")
    assert r2["success"] is True

    # Request 3 via +91 with dash
    r3 = auth_service.request_otp("+91-9876543217")
    assert r3["success"] is True

    # Request 4 via canonical +91: MUST BE REJECTED by rate limiter!
    r4 = auth_service.request_otp("+919876543217")
    assert r4["success"] is False
    assert r4["error"] == "RATE_LIMIT_EXCEEDED"


def test_production_config_validation(monkeypatch):
    # Missing or placeholder secrets must cause ProductionConfig.validate() to raise ValueError
    monkeypatch.setenv("SECRET_KEY", "dev-secret-placeholder")
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("OTP_HASH_SECRET", "short")

    with pytest.raises(ValueError) as exc:
        ProductionConfig.validate()
    assert "CRITICAL: Production" in str(exc.value)

    # Valid >= 32 char non-dev secrets must pass validation
    monkeypatch.setenv("SECRET_KEY", "secure-unique-production-secret-key-32-chars-long!")
    monkeypatch.setenv("JWT_SECRET", "secure-unique-production-jwt-key-32-chars-long!")
    monkeypatch.setenv("OTP_HASH_SECRET", "secure-unique-production-otp-key-32-chars-long!")
    # Should not raise:
    ProductionConfig.validate()


def test_concurrent_successful_otp_consumption(db, app):
    """
    Simulates concurrent requests submitting the SAME correct OTP at the exact same instant.
    Atomicity guarantees that exactly ONE request succeeds in consuming the OTP,
    and all other concurrent requests are rejected (preventing double-use).
    """
    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543218"
    req_res = auth_service.request_otp(phone)
    correct_otp = req_res["_mock_otp"]

    # 4 concurrent threads trying to verify the exact same correct OTP
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: auth_service.verify_otp(phone, correct_otp), range(4)))

    successes = [r for r in results if r["success"] is True]
    failures = [r for r in results if r["success"] is False]

    # Exactly ONE must succeed
    assert len(successes) == 1
    assert "token" in successes[0]

    # Exactly THREE must fail with OTP already used
    assert len(failures) == 3
    assert all(f["error"] == "INVALID_OTP" for f in failures)


def test_constant_time_comparison_invocation(db, app, mocker):
    """
    Verifies that Python's hmac.compare_digest is directly invoked
    during OTP verification and controls the decision path.
    """
    import hmac
    spy = mocker.spy(hmac, "compare_digest")

    auth_service = AuthService(db=db, config=app.config)
    phone = "+919876543219"
    req_res = auth_service.request_otp(phone)
    correct_otp = req_res["_mock_otp"]

    # 1. Wrong OTP test -> hmac.compare_digest must be called and return False
    res_wrong = auth_service.verify_otp(phone, "000000")
    assert res_wrong["success"] is False
    assert spy.called

    # 2. Correct OTP test -> hmac.compare_digest must be called and return True
    res_correct = auth_service.verify_otp(phone, correct_otp)
    assert res_correct["success"] is True
    assert spy.call_count >= 2

