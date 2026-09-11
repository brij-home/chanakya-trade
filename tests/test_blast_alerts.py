"""Unit & integration tests for Blast Alerts actionable profit blueprint and Telegram push notifications."""

from unittest.mock import patch, MagicMock
from bot.telegram_bot import format_blast_alert, send_blast_push


def test_format_blast_alert_call():
    blast_data = {
        "contract": "NIFTY 23550 CE",
        "action_title": "BUY NIFTY 23550 CE",
        "action_recommendation": "BUY (CALL MOMENTUM)",
        "score": 88,
        "blast_reason": "Call writers shedding 42,000 OI with 3.4x Vol/OI turnover",
        "imbalance_ratio": 3.2,
        "vol_oi_ratio": 3.4,
        "entry_range": "₹85.50 – ₹92.70",
        "stop_loss": 67.50,
        "stop_loss_pct": "-25.0%",
        "target_1": 117.0,
        "target_1_pct": "+30.0%",
        "target_2": 142.5,
        "target_2_pct": "+58.3%",
        "risk_reward": "1:2.5",
        "when_to_buy": "Enter on Ask/Retest (₹85.50 – ₹92.70) while Spot holds > ₹23,450",
        "when_to_wait": "DO NOT CHASE if premium > ₹105.00. Wait for pullback to ₹85.50",
        "profit_rule": "Book 50% profit at Target 1 (₹117.00), trail Stop Loss to Cost for Target 2",
    }
    html = format_blast_alert(blast_data, underlying="NIFTY", spot=23540.0)
    assert "NIFTY 23550 CE" in html
    assert "Entry Zone:" in html
    assert "₹85.50 – ₹92.70" in html
    assert "Invalidation SL:" in html
    assert "Target 1 (1.5R):" in html
    assert "Playbook:" in html
    assert "GAMMA BLAST SURGE" in html
    assert "Chanakya" not in html


def test_format_blast_alert_put():
    blast_data = {
        "contract": "NIFTY 23400 PE",
        "action_title": "BUY NIFTY 23400 PE",
        "action_recommendation": "BUY (PUT BREAKDOWN)",
        "score": 91,
        "blast_reason": "Put writers liquidating 50,000 OI with 4.1x Vol/OI",
        "imbalance_ratio": 4.1,
        "vol_oi_ratio": 4.1,
        "entry_range": "₹60.00 – ₹65.00",
        "stop_loss": 45.0,
        "stop_loss_pct": "-25.0%",
        "target_1": 85.0,
        "target_1_pct": "+30.0%",
        "target_2": 110.0,
        "target_2_pct": "+69.2%",
        "risk_reward": "1:2.5",
        "when_to_buy": "Enter on Ask/Retest while Spot breaks lower",
        "when_to_wait": "DO NOT CHASE if premium spiked > 15%",
        "profit_rule": "Book 50% profit at Target 1, trail SL to Cost",
    }
    html = format_blast_alert(blast_data, underlying="NIFTY", spot=23420.0)
    assert "NIFTY 23400 PE" in html
    assert "Target 1 (1.5R):" in html
    assert "BUY NIFTY 23400 PE" in html
    assert "Invalidation SL:" in html


def test_send_blast_push_mocked():
    blast_data = {
        "contract": "NIFTY 23550 CE",
        "entry_range": "₹85.00 – ₹92.00",
        "stop_loss": 65.0,
        "target_1": 115.0,
        "target_2": 140.0,
        "risk_reward": "1:2.5",
        "when_to_buy": "Buy on pullback",
        "profit_rule": "Take 50% at T1",
    }
    with patch(
        "config.credentials.get_credential",
        side_effect=lambda k: "fake_val" if "TELEGRAM" in k else None,
    ):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: {"ok": True, "result": {}}
            )
            res = send_blast_push(blast_data, underlying="NIFTY", spot=23500.0)
            assert res is True
