"""
tests/test_index_hedging_filter.py
───────────────────────────────────
Verifies that directional index signals (NIFTY, BANKNIFTY, MIDCPNIFTY, etc.)
are suppressed when FNO_INDEX is disabled, while dedicated portfolio/delta
hedging signals remain permitted across all channels.
"""

from __future__ import annotations

import pytest
from engine.alert_preferences import AlertPreferences, AlertPreferencesManager, classify_alert_segment
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine


def test_index_directional_blocked_hedging_permitted(tmp_path):
    """Directional index signals blocked, hedging index signals permitted when FNO_INDEX disabled."""
    test_pref_file = tmp_path / "test_alert_prefs.json"

    mgr = AlertPreferencesManager()
    mgr._pref_file = test_pref_file
    mgr._preferences = AlertPreferences()

    # Disable FNO_INDEX across all channels (user mandate)
    filtered_segments = ["FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY", "CRYPTO"]
    mgr.update_preferences(
        {
            "allowed_segments": filtered_segments,
            "ui": {"allowed_segments": filtered_segments},
            "telegram": {"allowed_segments": filtered_segments},
            "desktop": {"allowed_segments": filtered_segments},
            "sound": {"allowed_segments": filtered_segments},
        }
    )

    assert mgr.is_segment_allowed("FNO_INDEX", "ui") is False
    assert mgr.is_segment_allowed("FNO_INDEX", "telegram") is False
    assert mgr.is_segment_allowed("FNO_STOCK", "ui") is True

    # 1. Directional BankNifty Call alert (should be BLOCKED)
    dir_bn_alert = {
        "symbol": "BANKNIFTY",
        "contract_symbol": "BANKNIFTY56500CE",
        "option_type": "CE",
        "confidence": 85,
        "stage": "IGNITED",
        "is_hedge": False,
    }
    assert classify_alert_segment(dir_bn_alert) == "FNO_INDEX"
    assert mgr.is_alert_allowed(dir_bn_alert, "ui") is False
    assert mgr.is_alert_allowed(dir_bn_alert, "telegram") is False

    # 2. Directional MidcpNifty Put alert (should be BLOCKED)
    dir_midcp_alert = {
        "symbol": "MIDCPNIFTY",
        "contract_symbol": "MIDCPNIFTY14475PE",
        "option_type": "PE",
        "confidence": 85,
        "stage": "IGNITED",
        "is_hedge": False,
    }
    assert classify_alert_segment(dir_midcp_alert) == "FNO_INDEX"
    assert mgr.is_alert_allowed(dir_midcp_alert, "ui") is False
    assert mgr.is_alert_allowed(dir_midcp_alert, "telegram") is False

    # 3. Dedicated Index Portfolio / Delta Hedge alert (should be PERMITTED!)
    hedge_alert = {
        "symbol": "NIFTY",
        "contract_symbol": "NIFTY23400PE",
        "option_type": "PE",
        "confidence": 85,
        "stage": "IGNITED",
        "is_hedge": True,
        "purpose": "HEDGE",
    }
    assert classify_alert_segment(hedge_alert) == "FNO_INDEX"
    assert mgr.is_alert_allowed(hedge_alert, "ui") is True
    assert mgr.is_alert_allowed(hedge_alert, "telegram") is True

    # 4. Hedging alert via actionable_plan flag (should be PERMITTED!)
    hedge_plan_alert = {
        "symbol": "BANKNIFTY",
        "contract_symbol": "BANKNIFTY56000PE",
        "option_type": "PE",
        "confidence": 85,
        "stage": "IGNITED",
        "actionable_plan": {"is_hedge": True, "action": "PORTFOLIO_HEDGE"},
    }
    assert mgr.is_alert_allowed(hedge_plan_alert, "ui") is True
    assert mgr.is_alert_allowed(hedge_plan_alert, "telegram") is True

    # 5. Stock F&O alert (should be PERMITTED as normal)
    stk_alert = {
        "symbol": "RELIANCE",
        "contract_symbol": "RELIANCE1240CE",
        "option_type": "CE",
        "confidence": 85,
        "stage": "IGNITED",
    }
    assert classify_alert_segment(stk_alert) == "FNO_STOCK"
    assert mgr.is_alert_allowed(stk_alert, "ui") is True
    assert mgr.is_alert_allowed(stk_alert, "telegram") is True

    # 6. Cash Equity alert (should be PERMITTED as normal)
    eq_alert = {
        "symbol": "TATASTEEL",
        "exchange": "NSE",
        "confidence": 85,
        "stage": "IGNITED",
    }
    assert classify_alert_segment(eq_alert) == "EQUITY"
    assert mgr.is_alert_allowed(eq_alert, "ui") is True
    assert mgr.is_alert_allowed(eq_alert, "telegram") is True


def test_scanner_omits_indices_when_fno_index_disabled(monkeypatch, tmp_path):
    """Scanner targets should exclude index symbols when FNO_INDEX is disabled."""
    from engine.alert_preferences import alert_preferences

    monkeypatch.setattr(alert_preferences, "_pref_file", tmp_path / "prefs.json")
    
    # When FNO_INDEX is disabled:
    alert_preferences.update_preferences(
        {
            "allowed_segments": ["FNO_STOCK", "EQUITY"],
            "ui": {"allowed_segments": ["FNO_STOCK", "EQUITY"]},
        }
    )
    assert alert_preferences.is_segment_allowed("FNO_INDEX") is False

    engine = AutoAlertEngine()
    targets = engine._get_prioritized_targets()
    for idx in ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKEX"]:
        assert idx not in targets, f"Index {idx} should NOT be in scanner targets when FNO_INDEX is disabled!"

    # Equities should still be present
    assert "RELIANCE" in targets
    assert "TCS" in targets

    # When FNO_INDEX is re-enabled:
    alert_preferences.update_preferences(
        {
            "allowed_segments": ["FNO_INDEX", "FNO_STOCK", "EQUITY"],
            "ui": {"allowed_segments": ["FNO_INDEX", "FNO_STOCK", "EQUITY"]},
        }
    )
    assert alert_preferences.is_segment_allowed("FNO_INDEX") is True
    targets_with_index = engine._get_prioritized_targets()
    assert any(idx in targets_with_index for idx in ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"])


def test_from_dict_persists_fno_index_exclusion():
    """AlertPreferences.from_dict must not re-inject FNO_INDEX if excluded."""
    data = {
        "allowed_segments": ["FNO_STOCK", "EQUITY", "COMMODITY"],
        "ui": {"allowed_segments": ["FNO_STOCK", "EQUITY"]},
        "telegram": {"allowed_segments": ["FNO_STOCK"]},
    }
    prefs = AlertPreferences.from_dict(data)
    assert "FNO_INDEX" not in prefs.allowed_segments
    assert "FNO_INDEX" not in prefs.ui.allowed_segments
    assert "FNO_STOCK" in prefs.allowed_segments


def test_index_options_permitted_futures_blocked(tmp_path):
    """When FNO_INDEX is enabled, index options and hedges are permitted, but naked index futures are blocked."""
    test_pref_file = tmp_path / "test_alert_prefs.json"

    mgr = AlertPreferencesManager()
    mgr._pref_file = test_pref_file
    mgr._preferences = AlertPreferences()

    all_segments = ["FNO_INDEX", "FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY", "CRYPTO"]
    mgr.update_preferences(
        {
            "allowed_segments": all_segments,
            "ui": {"allowed_segments": all_segments},
            "telegram": {"allowed_segments": all_segments, "min_confidence": 80},
        }
    )

    # 1. Index Option (NIFTY Call) -> MUST BE PERMITTED!
    nifty_opt = {
        "symbol": "NIFTY",
        "contract_symbol": "NIFTY23400CE",
        "option_type": "CE",
        "alert_type": "OPTIONS_MOMENTUM",
        "confidence": 95,
        "stage": "IGNITED",
        "is_hedge": False,
    }
    assert mgr.is_alert_allowed(nifty_opt, "ui") is True
    assert mgr.is_alert_allowed(nifty_opt, "telegram") is True

    # 2. Index Option (BANKNIFTY Put) -> MUST BE PERMITTED!
    bn_opt = {
        "symbol": "BANKNIFTY",
        "contract_symbol": "BANKNIFTY56000PE",
        "option_type": "PE",
        "alert_type": "GAMMA_BLAST",
        "confidence": 92,
        "stage": "IGNITED",
        "is_hedge": False,
    }
    assert mgr.is_alert_allowed(bn_opt, "ui") is True
    assert mgr.is_alert_allowed(bn_opt, "telegram") is True

    # 3. Naked Directional Index Future (BANKNIFTY Futures) -> MUST BE BLOCKED!
    bn_fut = {
        "symbol": "BANKNIFTY",
        "contract_symbol": "BANKNIFTY26SEPFUT",
        "derivative_type": "FUT",
        "alert_type": "INDEX_FUTURES",
        "action": "BUY_FUTURES",
        "confidence": 95,
        "stage": "IGNITED",
        "is_hedge": False,
    }
    assert mgr.is_alert_allowed(bn_fut, "ui") is False
    assert mgr.is_alert_allowed(bn_fut, "telegram") is False

    # 4. Hedging Index Future (NIFTY Short Futures for Portfolio Hedge) -> MUST BE PERMITTED!
    hedge_fut = {
        "symbol": "NIFTY",
        "contract_symbol": "NIFTY26SEPFUT",
        "derivative_type": "FUT",
        "action": "SELL_SHORT_FUTURES",
        "confidence": 95,
        "stage": "IGNITED",
        "is_hedge": True,
        "purpose": "HEDGE",
    }
    assert mgr.is_alert_allowed(hedge_fut, "ui") is True
    assert mgr.is_alert_allowed(hedge_fut, "telegram") is True

