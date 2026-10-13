"""Unit tests for pure helpers: money, TOTP, encryption, OTP hashing, i18n, rate limiting, order rules."""
from decimal import Decimal

import pytest

from src.core import totp
from src.core.crypto import encrypt, decrypt, mask, hash_secret, verify_secret
from src.core.i18n import render, status_label, normalize_language
from src.core.money import D, money, to_paise
from src.core.rate_limit import SlidingWindowLimiter


def test_money_rounds_half_up_and_converts_to_paise():
    assert money("2.345") == Decimal("2.35")
    assert money(None) == Decimal("0.00")
    assert to_paise("2200") == 220000 and to_paise("0.015") == 2
    assert D(0.1) + D(0.2) == Decimal("0.3")  # no float drift


def test_totp_round_trip_and_rejects_wrong_codes():
    secret = totp.generate_secret()
    assert totp.verify(secret, totp.current_code(secret))
    assert not totp.verify(secret, "000000") or totp.current_code(secret) == "000000"
    assert not totp.verify(secret, "abc")
    assert totp.provisioning_uri(secret, "a@b.c").startswith("otpauth://totp/")


def test_rfc6238_reference_vector():
    # RFC 6238 test secret "12345678901234567890" (base32 GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ) at T=59s -> 287082 (6 digits)
    assert totp.current_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=59) == "287082"


def test_field_encryption_and_masking():
    token = encrypt("123456789012")
    assert token != "123456789012" and decrypt(token) == "123456789012"
    assert encrypt(None) is None and decrypt(None) is None
    assert mask("123456789012") == "••••••••9012"


def test_secrets_are_hashed_not_stored():
    hashed = hash_secret("482913")
    assert "482913" not in hashed and verify_secret("482913", hashed)
    assert not verify_secret("482914", hashed) and not verify_secret("482913", None)


def test_i18n_renders_telugu_and_falls_back():
    title, message = render("order_status", "te", order_number="ORD-1", status="delivered")
    assert "ఆర్డర్" in title and "డెలివరీ అయింది" in message
    assert render("order_status", "fr", order_number="ORD-1", status="delivered")[0] == "Order update"
    assert normalize_language("te-IN,en;q=0.8") == "te"
    assert status_label("in_transit", "en") == "In transit"
    # Missing parameters never raise.
    assert render("offer_received", "en")[1].startswith("{party}")


def test_rate_limiter_sliding_window():
    limiter = SlidingWindowLimiter()
    assert all(limiter.allow("k", 3, 60) for _ in range(3))
    assert not limiter.allow("k", 3, 60)
    assert limiter.allow("other", 3, 60)


def test_order_transition_rules_are_consistent():
    from src.data_models.orders_model import ORDER_STATUSES
    from src.services.order_core import TRANSITIONS

    for (from_status, to_status), parties in TRANSITIONS.items():
        assert from_status in ORDER_STATUSES and to_status in ORDER_STATUSES
        assert parties <= {"farmer", "vendor", "admin", "system"}
    # A completed order can never be cancelled directly; disputes go through their own workflow.
    assert ("completed", "cancelled") not in TRANSITIONS
    assert ("delivered", "cancelled") not in TRANSITIONS


@pytest.mark.parametrize("raw,ok", [("+919812345678", True), ("9812345678", True), ("12", False)])
def test_phone_normalisation(raw, ok):
    import re
    from src.services.login_service import normalize_phone

    assert bool(re.fullmatch(r"\+\d{10,15}", normalize_phone(raw) or "")) is ok
