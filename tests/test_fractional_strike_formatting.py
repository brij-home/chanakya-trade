"""
tests/test_fractional_strike_formatting.py
──────────────────────────────────────────
Institutional test suite validating end-to-end precision for fractional and decimal
option strikes across Indian Markets (NSE, BSE, NFO, MCX, CDS).

Verifies the fix for the ASHOKLEY 142.5 PE issue where strikes were historically
truncated to int(strike) (e.g. 142 PE) instead of 142.5 PE.
"""

import re

from market.instruments import format_strike
from bot.alert_templates import (
    format_contract_display,
    parse_contract_components,
    format_signal_badge_and_lot,
    render_auto_alert,
)
from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.strike_revolver import derive_new_contract_symbol


class TestFormatStrikeSSOT:
    """Validate canonical format_strike helper under various strike inputs."""

    def test_integer_strikes(self):
        assert format_strike(24500) == "24500"
        assert format_strike(24500.0) == "24500"
        assert format_strike("24500") == "24500"
        assert format_strike("24500.0") == "24500"
        assert format_strike(140.0) == "140"
        assert format_strike(500) == "500"

    def test_half_decimal_strikes(self):
        # Ashok Leyland, BEL, BHEL, Tata Steel, etc.
        assert format_strike(142.5) == "142.5"
        assert format_strike(142.50) == "142.5"
        assert format_strike("142.5") == "142.5"
        assert format_strike(287.5) == "287.5"
        assert format_strike(7.5) == "7.5"
        assert format_strike(8.5) == "8.5"

    def test_multi_decimal_strikes(self):
        # Currency / USDINR (0.25 steps) / MCX commodities
        assert format_strike(83.25) == "83.25"
        assert format_strike(83.75) == "83.75"
        assert format_strike(242.5) == "242.5"

    def test_edge_cases(self):
        assert format_strike(0) == "0"
        assert format_strike(0.0) == "0"
        assert format_strike(None) == ""
        assert format_strike("") == ""
        assert format_strike("INVALID") == "INVALID"


class TestAlertTemplatesFractionalStrikes:
    """Validate contract parsing and display formatting in bot/alert_templates.py."""

    def test_format_display_contract_fractional(self):
        # Monthly contract with decimal strike
        assert format_contract_display("ASHOKLEY26NOV142.5PE") == "ASHOKLEY 142.5 PE"
        assert format_contract_display("ASHOKLEY26NOV142.5CE") == "ASHOKLEY 142.5 CE"
        assert format_contract_display("IDEA26NOV7.5CE") == "IDEA 7.5 CE"

        # Already space-separated
        assert format_contract_display("ASHOKLEY 142.5 PE") == "ASHOKLEY 142.5 PE"
        assert format_contract_display("BEL 287.5 CE") == "BEL 287.5 CE"

        # Broker YYYYMMDD format
        assert format_contract_display("ASHOKLEY20261126142.5PE") == "ASHOKLEY 142.5 PE"

        # Integer strikes remain clean integers
        assert format_contract_display("NIFTY26NOV24500CE") == "NIFTY 24500 CE"
        assert format_contract_display("ASHOKLEY26NOV140PE") == "ASHOKLEY 140 PE"

    def test_parse_contract_components_fractional(self):
        parsed = parse_contract_components("ASHOKLEY26NOV142.5PE")
        assert parsed is not None
        assert parsed["underlying"] == "ASHOKLEY"
        assert float(parsed["strike"]) == 142.5
        assert parsed["option_type"] == "PE"

        parsed_idea = parse_contract_components("IDEA26NOV7.5CE")
        assert parsed_idea is not None
        assert parsed_idea["underlying"] == "IDEA"
        assert float(parsed_idea["strike"]) == 7.5
        assert parsed_idea["option_type"] == "CE"

        parsed_iso = parse_contract_components("ASHOKLEY20261126142.5PE")
        assert parsed_iso is not None
        assert parsed_iso["underlying"] == "ASHOKLEY"
        assert float(parsed_iso["strike"]) == 142.5
        assert parsed_iso["option_type"] == "PE"

    def test_format_signal_badge_and_lot_fractional(self):
        badge = format_signal_badge_and_lot(
            "🔴 [TREND PULLBACK] ASHOKLEY 142.5 PE Buy: 20-EMA Reject", "ASHOKLEY"
        )
        assert "142.5 PE" in badge
        assert "5000" in badge  # Lot size injected for ASHOKLEY
        assert "142 PE" not in badge


class TestStrikeRevolverFractional:
    """Validate dynamic strike rolling with decimal strikes."""

    def test_derive_new_contract_symbol(self):
        orig = "ASHOKLEY26NOV140PE"
        rolled = derive_new_contract_symbol(orig, "ASHOKLEY", "PE", 140.0, 142.5)
        assert rolled == "ASHOKLEY26NOV142.5PE"

        rolled_back = derive_new_contract_symbol(
            "ASHOKLEY26NOV142.5PE", "ASHOKLEY", "PE", 142.5, 145.0
        )
        assert rolled_back == "ASHOKLEY26NOV145PE"


class TestAlertIdentityFractional:
    """Validate alert ID generation ensures uniqueness and clean slugs for fractional strikes."""

    def test_generate_alert_id_with_decimal_variant(self):
        from datetime import date

        alert_id = generate_alert_id(
            alert_type="TREND_PULLBACK",
            symbol="ASHOKLEY",
            variant="142.5 PE",
            session_date=date(2026, 10, 26),
        )
        # Decimal point converted to 'p' to prevent collision with 1425
        assert "142p5" in alert_id
        assert "." not in alert_id
        assert alert_id == "aa-trend-pullback-ashokley-142p5-pe-20261026"

        # Integer strike variant
        alert_id_140 = generate_alert_id(
            alert_type="TREND_PULLBACK",
            symbol="ASHOKLEY",
            variant="140 PE",
            session_date=date(2026, 10, 26),
        )
        assert "140-pe" in alert_id_140
        assert alert_id != alert_id_140


class TestAutoAlertModelPostInitFractional:
    """Validate AutoAlert post-init strike extraction and headline parsing."""

    def test_auto_alert_extracts_decimal_strike(self):
        alert = AutoAlert(
            alert_id="aa-trend-pullback-ashokley-142p5-pe-20261026",
            alert_type="TREND_PULLBACK",
            stage="IGNITED",
            symbol="NSE:ASHOKLEY",
            exchange="NSE",
            direction="BEARISH",
            headline="🔴 [TREND PULLBACK] ASHOKLEY 142.5 PE (Lot: 5000) Buy: 20-EMA Resistance Reject (Spot ₹141.6) | Opt CMP: ₹6.54",
            summary="Institutional shallow bounce into falling 20-EMA/VWAP on ASHOKLEY. Enter ASHOKLEY 142.5 PE @ ₹6.54.",
            strike=142.5,
            option_type="PE",
            contract_symbol="ASHOKLEY26NOV142.5PE",
            ltp=6.54,
            trigger_level=6.54,
            stop_loss=5.6,
            target_level=7.98,
            lot_size=5000,
        )

        assert alert.strike == 142.5
        assert alert.option_type == "PE"
        assert "142.5 PE" in alert.headline
        assert "142 PE" not in alert.headline


class TestEndToEndAshokleyAlertFormatting:
    """Validate full Telegram message rendering for ASHOKLEY 142.5 PE."""

    def test_ashokley_telegram_message_contains_no_truncated_strike(self):
        alert = AutoAlert(
            alert_id="aa-trend-pullback-ashokley-142p5-pe-20261026",
            alert_type="TREND_PULLBACK",
            stage="IGNITED",
            symbol="NSE:ASHOKLEY",
            exchange="NSE",
            direction="BEARISH",
            headline="🔴 [TREND PULLBACK] ASHOKLEY 142.5 PE Buy: 20-EMA Resistance Reject (Spot ₹141.6) | Opt CMP: ₹6.54",
            summary="Institutional shallow bounce into falling 20-EMA/VWAP on ASHOKLEY. Low-volume retest rejected at resistance. Enter ASHOKLEY 142.5 PE @ ₹6.54. Stop loss: ₹5.6. (R:R 2.0)",
            strike=142.5,
            option_type="PE",
            contract_symbol="ASHOKLEY26NOV142.5PE",
            underlying_spot=141.56,
            ltp=6.54,
            trigger_level=6.54,
            stop_loss=5.6,
            target_level=7.98,
            lot_size=5000,
            expiry_date="2026-11-26",
            created_at="2026-10-26 11:35:00",
        )

        msg = render_auto_alert(alert)

        # 1. Headline check
        assert "142.5 PE" in msg
        # 2. Action line check
        assert "ASHOKLEY26NOV142.5PE" in msg or "142.5 PE" in msg
        # 3. Check for absence of truncated "142 PE" (ensuring word/space boundary so 142.5 is not matched)
        assert not re.search(r"\b142\s+PE\b", msg), (
            "Found truncated '142 PE' in formatted Telegram message!"
        )
        # 4. Check hashtag
        assert "142.5PE" in msg or "142p5" in msg or "142_5PE" in msg
