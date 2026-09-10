import datetime as dt

from pi_pipeline.config import Settings


def _s(expires="", warn_days=30):
    s = Settings()
    object.__setattr__(s, "api_key_expires", expires)          # Settings is frozen
    object.__setattr__(s, "api_key_expiry_warn_days", warn_days)
    return s


TODAY = dt.date(2026, 9, 10)


def test_unset_is_silent():
    lvl, msg = _s("").api_key_expiry_status(TODAY)
    assert lvl == "unset" and msg == ""


def test_far_future_is_ok_and_silent():
    lvl, msg = _s("2027-09-10").api_key_expiry_status(TODAY)
    assert lvl == "ok" and msg == ""


def test_within_warn_window():
    lvl, msg = _s("2026-10-05").api_key_expiry_status(TODAY)   # 25 days out
    assert lvl == "warn"
    assert "expires in 25 day" in msg and "2026-10-05" in msg


def test_boundary_is_a_warning():
    lvl, _ = _s("2026-10-10", warn_days=30).api_key_expiry_status(TODAY)  # exactly 30
    assert lvl == "warn"


def test_expired():
    lvl, msg = _s("2026-09-01").api_key_expiry_status(TODAY)
    assert lvl == "expired"
    assert "expired 9 day(s) ago" in msg and "Create a new key" in msg


def test_malformed_disables_the_check():
    lvl, msg = _s("next tuesday").api_key_expiry_status(TODAY)
    assert lvl == "malformed" and "not a YYYY-MM-DD" in msg


def test_custom_warn_days():
    lvl, _ = _s("2026-12-01", warn_days=120).api_key_expiry_status(TODAY)  # ~82 days
    assert lvl == "warn"
    lvl, _ = _s("2026-12-01", warn_days=30).api_key_expiry_status(TODAY)
    assert lvl == "ok"
