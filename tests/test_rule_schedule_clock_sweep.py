"""Contract tests for Dec 7, 2026 CAS & derivative close rule_schedule clock migration."""

from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def test_rule_schedule_entry_and_squareoff_cutoffs_respect_dec7_boundary():
    from market.rule_schedule import (
        derivative_close,
        intraday_entry_cutoff,
        intraday_squareoff_cutoff,
        is_cas_window,
    )

    pre = date(2026, 11, 25)
    post = date(2026, 12, 7)

    # Pre-Dec 7: both derivative and cash cutoffs remain 15:15 (30m CAS is 15:15-15:25)
    assert intraday_entry_cutoff(pre, is_derivative=True) == dtime(15, 15)
    assert intraday_squareoff_cutoff(pre, is_derivative=False) == dtime(15, 15)
    assert is_cas_window(datetime(2026, 11, 25, 15, 20, tzinfo=IST)) is True

    # Dec 7+: non-expiring derivatives close at 15:45 (cutoff 15:30); expiring index closes 15:30 (cutoff 15:15)
    assert derivative_close(post, expiring_index=False) == dtime(15, 45)
    assert derivative_close(post, expiring_index=True) == dtime(15, 30)
    assert intraday_entry_cutoff(post, is_derivative=True, expiring_index=False) == dtime(15, 30)
    assert intraday_entry_cutoff(post, is_derivative=True, expiring_index=True) == dtime(15, 15)
    assert intraday_entry_cutoff(post, is_derivative=False) == dtime(15, 15)
    assert is_cas_window(datetime(2026, 12, 7, 15, 35, tzinfo=IST)) is True


def test_session_runway_and_dynamics_governor_extend_cleanly_after_dec7():
    from engine.session_runway import get_current_session_phase, is_session_runway_sufficient
    from engine.market_dynamics_governor import get_intraday_phase

    # 15:20 IST on Dec 7, 2026 (non-expiring derivative): still active pre-15:30 runway!
    dt_post = datetime(2026, 12, 7, 15, 20, tzinfo=IST)
    phase, rem = get_current_session_phase(dt_post)
    assert phase == "SESSION_RUNWAY_EXHAUSTION"
    assert rem == 10
    assert get_intraday_phase(dt_post) == "EXPIRY_0DTE_GAMMA_UNPIN"

    ok_fno, _ = is_session_runway_sufficient(
        "GAMMA_BLAST",
        asset_class="FNO_INDEX",
        current_time=dt_post.time(),
        ref_date=dt_post.date(),
    )
    assert ok_fno is True

    # Cash equity at 15:20 IST on Dec 7 still stops cleanly at 15:15 MIS cutoff
    ok_eq, reason_eq = is_session_runway_sufficient(
        "INTRADAY_EQUITY",
        asset_class="EQUITY",
        current_time=dt_post.time(),
        ref_date=dt_post.date(),
    )
    assert ok_eq is False
    assert "runway" in reason_eq.lower() or "square-off" in reason_eq.lower()
