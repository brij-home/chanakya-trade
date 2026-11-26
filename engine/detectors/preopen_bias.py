from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Optional

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type
from market.instruments import format_strike
from engine.daily_levels import get_daily_levels, detect_virgin_cpr

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_BIAS_THRESHOLD_PCT = 0.30
_STRONG_BIAS_PCT = 0.60
_INDEX_UNIVERSE = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})


def detect_preopen_bias(
    underlying: str,
    gift_futures_price: float,
    prev_close: float,
    chain: Optional[list[Any]] = None,
    atm_ce_ltp: Optional[float] = None,
    atm_pe_ltp: Optional[float] = None,
    atm_strike: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Automated Pre-Open 09:08 IST Radar.
    Fuses GIFT Nifty indicative price discovery, Central Pivot Range (CPR),
    Untested Virgin CPR Magnets, and GEX/DEX Pinning into a decisive Opening Archetype blueprint.
    """
    clean_sym = canonical_alert_symbol(underlying)
    if clean_sym not in _INDEX_UNIVERSE:
        return []
    if gift_futures_price <= 0 or prev_close <= 0:
        return []

    now_dt = datetime.now(IST)
    is_preopen = now_dt.hour == 9 and 5 <= now_dt.minute <= 14
    is_test = os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
    if not is_preopen and not is_test:
        return []

    gap_pct = (gift_futures_price - prev_close) / prev_close * 100.0
    abs_gap = abs(gap_pct)
    if abs_gap < _BIAS_THRESHOLD_PCT:
        return []

    is_bullish = gap_pct > 0
    signal_type = "PREOPEN_CALL_BIAS" if is_bullish else "PREOPEN_PUT_BIAS"
    option_type = "CE" if is_bullish else "PE"
    direction = "BULLISH" if is_bullish else "BEARISH"
    strength = "STRONG" if abs_gap >= _STRONG_BIAS_PCT else "MODERATE"

    # 1. CPR & Virgin CPR Integration
    dl = None
    try:
        dl = get_daily_levels(clean_sym)
    except Exception as e_dl:
        logger.debug(f"[PreopenBias] DailyLevels lookup note for {clean_sym}: {e_dl}")

    cpr_info = dl.cpr if dl else {}
    cpr_width_pct = float(cpr_info.get("width_pct", 0.0) or 0.0)
    is_narrow = bool(cpr_info.get("is_narrow", False))
    is_wide = bool(cpr_info.get("is_wide", False))
    cpr_top = float(cpr_info.get("top", 0.0) or 0.0)
    cpr_bottom = float(cpr_info.get("bottom", 0.0) or 0.0)
    cpr_pivot = float(cpr_info.get("pivot", 0.0) or 0.0)
    cpr_type = str(
        cpr_info.get("cpr_type", "NARROW" if is_narrow else ("WIDE" if is_wide else "NORMAL"))
    )

    virgin_cpr: dict[str, Any] = (
        dl.virgin_cpr
        if dl and getattr(dl, "virgin_cpr", None)
        else (cpr_info.get("virgin_cpr") or {})
    )
    if not virgin_cpr:
        try:
            virgin_cpr = detect_virgin_cpr(clean_sym, current_price=gift_futures_price)
        except Exception as e_vc:
            logger.debug(f"[PreopenBias] Virgin CPR detection note: {e_vc}")
            virgin_cpr = {}

    # 2. GEX & Dealer Delta Exposure (DEX) Fusion
    gex_data: dict[str, Any] = {}
    try:
        if chain:
            from market.options import compute_chain_gex

            gex_data = compute_chain_gex(clean_sym, chain) or {}
        if not gex_data:
            from analysis.gex import get_gex_analysis

            gex_res = get_gex_analysis(clean_sym, spot=gift_futures_price)
            if gex_res:
                gex_data = gex_res.to_dict()
    except Exception as e_gex:
        logger.debug(f"[PreopenBias] GEX lookup note: {e_gex}")

    call_wall = float(gex_data.get("call_wall", 0.0) or 0.0)
    put_wall = float(gex_data.get("put_wall", 0.0) or 0.0)
    zero_gamma = float(gex_data.get("zero_gamma_level") or gex_data.get("gamma_flip") or 0.0)
    dex_regime = str(gex_data.get("dex_regime", "BALANCED"))
    dex_neutral = float(
        gex_data.get("dex_neutral_strike") or gex_data.get("dex_neutral_level") or 0.0
    )

    # 3. Classify Session Opening Day Archetype
    has_vcpr = bool(virgin_cpr.get("has_virgin_cpr"))
    vcpr_dist_pct = float(virgin_cpr.get("distance_pct", 999.0) or 999.0)
    vcpr_bias = str(virgin_cpr.get("magnet_bias", ""))

    if not is_bullish and zero_gamma > 0 and gift_futures_price < zero_gamma:
        day_archetype = "VOLATILITY_EXPANSION_CASCADE"
        archetype_reason = f"Opening below Zero-Gamma flip (₹{zero_gamma:,.1f}) triggers dealer short-gamma selling acceleration."
    elif is_bullish and call_wall > 0 and gift_futures_price >= call_wall * 0.998:
        day_archetype = "GAMMA_SQUEEZE_BREAKOUT"
        archetype_reason = (
            f"Opening at/above Call Wall (₹{call_wall:,.1f}) forces dealer short covering cascade."
        )
    elif is_narrow and abs_gap >= 0.25:
        day_archetype = "TREND_EXPANSION_DAY"
        archetype_reason = f"Narrow CPR ({cpr_width_pct:.2f}%) indicates high trending compression."
    elif (
        has_vcpr
        and vcpr_dist_pct <= 1.50
        and (
            (is_bullish and vcpr_bias == "MAGNET_BELOW")
            or (not is_bullish and vcpr_bias == "MAGNET_ABOVE")
        )
    ):
        day_archetype = "MEAN_REVERSION_MAGNET_DAY"
        archetype_reason = f"Active Virgin CPR at ₹{virgin_cpr.get('magnet_target', 0):,.1f} creates powerful opposing magnet."
    elif is_wide and abs_gap < 0.40:
        day_archetype = "PINNED_CHOP_DAY"
        archetype_reason = (
            f"Wide CPR ({cpr_width_pct:.2f}%) signals boundary containment / rangebound absorption."
        )
    elif abs_gap >= _STRONG_BIAS_PCT:
        day_archetype = "MOMENTUM_BREAKOUT_DAY"
        archetype_reason = (
            f"Strong gap ({gap_pct:+.2f}%) breaching regular volatility expectations."
        )
    else:
        day_archetype = "DIRECTIONAL_BIAS_DAY"
        archetype_reason = f"Directional gap ({gap_pct:+.2f}%) favoring {direction} opening drive."

    # 4. Conviction and Strike Selection
    base_confidence = 72 + (10 if abs_gap >= _STRONG_BIAS_PCT else 0)
    if day_archetype in (
        "TREND_EXPANSION_DAY",
        "VOLATILITY_EXPANSION_CASCADE",
        "GAMMA_SQUEEZE_BREAKOUT",
    ):
        base_confidence += 6
    if "SHORT_DELTA" in dex_regime and is_bullish:
        base_confidence += 4  # Short covering fuel
    elif "LONG_DELTA" in dex_regime and not is_bullish:
        base_confidence += 4  # Long unwinding cascade
    confidence = max(60, min(92, base_confidence))

    from market.symbol_master import get_strike_step

    step = get_strike_step(clean_sym, spot=gift_futures_price)

    if atm_strike is None or atm_strike <= 0:
        atm_strike = round(gift_futures_price / step) * step

    chosen_ltp = (atm_ce_ltp if is_bullish else atm_pe_ltp) or 0.0
    chosen_contract = None
    if chosen_ltp <= 0 and chain:
        cands = [
            c
            for c in chain
            if getattr(c, "option_type", "") == option_type
            and abs(getattr(c, "strike", 0) - atm_strike) <= step
            and getattr(c, "last_price", 0) > 0
        ]
        if cands:
            cands.sort(key=lambda c: abs(getattr(c, "strike", 0) - atm_strike))
            chosen_contract = cands[0]
            chosen_ltp = float(getattr(chosen_contract, "last_price", 0))
            atm_strike = float(getattr(chosen_contract, "strike", atm_strike))

    exp_date = None
    exp_type = "WEEKLY"
    if chain:
        wc = sorted(
            [c for c in chain if getattr(c, "option_type", "") == option_type],
            key=lambda c: str(getattr(c, "expiry", "")),
        )
        if wc:
            exp_date = getattr(wc[0], "expiry", None)
            exp_type = classify_expiry_type(exp_date, underlying) if exp_date else "WEEKLY"

    try:
        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(underlying) or 1
    except Exception:
        lot_sz = 1

    sl_prem = round(chosen_ltp * 0.82, 1) if chosen_ltp > 0 else 0.0
    t1_prem = round(chosen_ltp * 1.30, 1) if chosen_ltp > 0 else 0.0
    t2_prem = round(chosen_ltp * 1.60, 1) if chosen_ltp > 0 else 0.0
    no_chase = round(chosen_ltp * 1.06, 1) if chosen_ltp > 0 else 0.0
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    contract_sym = (
        getattr(chosen_contract, "symbol", None)
        or f"{clean_sym}{format_strike(atm_strike)}{option_type}"
    )
    bias_dir = "BULLISH GAP-UP" if is_bullish else "BEARISH GAP-DOWN"

    headline = f"[{day_archetype}] {strength} PREOPEN {bias_dir}: {clean_sym} {format_strike(atm_strike)} {option_type} SETUP"
    entry_str = f"Rs{chosen_ltp:.1f}" if chosen_ltp > 0 else "Await 09:15 open print"
    summary = (
        f"GIFT Nifty at Rs{gift_futures_price:.1f} ({gap_pct:+.2f}% vs prev close Rs{prev_close:.1f}). "
        f"Archetype: {day_archetype} ({archetype_reason}). "
        f"Entry: {entry_str} | SL: Rs{sl_prem:.1f} | T1: Rs{t1_prem:.1f} (+30%) | T2: Rs{t2_prem:.1f} (+60%). "
        f"Strength: {strength} ({abs_gap:.2f}%)"
    )

    a = AutoAlert(
        alert_id=generate_alert_id(
            clean_sym,
            "PREOPEN_BIAS",
            variant=f"{option_type.lower()}-{format_strike(atm_strike).replace('.', 'p')}",
        ),
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol=clean_sym,
        exchange="NFO",
        direction=direction,
        headline=headline,
        summary=f"{summary} | No Chase>Rs{no_chase:.1f}",
        ltp=chosen_ltp or gift_futures_price,
        trigger_level=chosen_ltp if chosen_ltp > 0 else atm_strike,
        target_level=t1_prem if t1_prem > 0 else 0,
        stop_loss=sl_prem if sl_prem > 0 else 0,
        no_chase_boundary=no_chase,
        strike=atm_strike,
        option_type=option_type,
        contract_symbol=contract_sym,
        expiry_date=exp_date,
        expiry_type=exp_type,
        underlying_spot=gift_futures_price,
        option_premium=chosen_ltp if chosen_ltp > 0 else None,
        market_status="PRE_OPEN",
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        lot_size=lot_sz,
        confidence=confidence,
        created_at=now_iso,
        ttl_seconds=3600,
        metrics={
            "signal_type": signal_type,
            "gift_futures_price": gift_futures_price,
            "prev_close": prev_close,
            "gap_pct": round(gap_pct, 3),
            "bias_strength": strength,
            "atm_strike": atm_strike,
            "option_type": option_type,
            "lot_size": lot_sz,
            "detector": "PREOPEN_BIAS",
            "day_archetype": day_archetype,
            "cpr_type": cpr_type,
            "cpr_width_pct": cpr_width_pct,
            "cpr_pivot": cpr_pivot,
            "virgin_cpr": virgin_cpr,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "zero_gamma_level": zero_gamma,
            "dex_regime": dex_regime,
            "dex_neutral_level": dex_neutral,
        },
        actionable_plan={
            "action": f"BUY {option_type} AT OPEN",
            "contract": contract_sym,
            "instrument": contract_sym,
            "instrument_type": "OPTION",
            "strike": atm_strike,
            "option_type": option_type,
            "expiry_date": exp_date,
            "expiry_type": exp_type,
            "day_archetype": day_archetype,
            "cpr_summary": f"{cpr_type} CPR ({cpr_width_pct:.2f}%) [₹{cpr_bottom:,.1f} - ₹{cpr_top:,.1f}]",
            "virgin_cpr_summary": virgin_cpr.get("summary", "No active untested virgin CPR"),
            "gex_pinning_summary": f"Call Wall: ₹{call_wall:,.0f} | Put Wall: ₹{put_wall:,.0f} | DEX: {dex_regime}"
            + (f" | Zero-Gamma: ₹{zero_gamma:,.0f}" if zero_gamma > 0 else ""),
            "recommended_entry": entry_str,
            "entry_rule": "Buy on 1-min candle CLOSE above opening VWAP (09:16-09:20 IST).",
            "no_chase": f"DO NOT CHASE above Rs{no_chase:.1f}",
            "target_1": f"Rs{t1_prem:.2f}",
            "target_2": f"Rs{t2_prem:.2f}",
            "stop_loss": f"Rs{sl_prem:.2f}",
            "risk_reward": "1:2.0 (estimated)",
            "session_context": f"PRE-OPEN | GIFT {gap_pct:+.2f}% | Archetype: {day_archetype} | Opens 09:15 IST",
        },
    )
    logger.info(
        f"[PreopenBias] [{day_archetype}] {signal_type}: {clean_sym} GIFT={gift_futures_price:.1f} ({gap_pct:+.2f}%) -> {format_strike(atm_strike)} {option_type}"
    )
    return [a]


def detect_preopen_stock_catalyst(
    symbol: str,
    preopen_price: float,
    prev_close: float,
    direction_bias: Optional[str] = None,
    sector_name: str = "",
    rrg_quadrant: str = "",
    min_gap_pct: float = 1.0,
    chain: Optional[list[Any]] = None,
) -> Optional[AutoAlert]:
    """
    Automated Single-Stock Pre-Open 09:08 IST Catalyst Radar.
    Surfaces high-conviction pre-market price discovery gaps in Tier-1 F&O stocks
    fused with bidirectional Sector RRG tailwinds before the 09:15 AM opening bell.
    """
    clean_sym = canonical_alert_symbol(symbol)
    if preopen_price <= 0 or prev_close <= 0:
        return None

    gap_pct = round((preopen_price - prev_close) / prev_close * 100.0, 2)
    abs_gap = abs(gap_pct)
    if abs_gap < min_gap_pct:
        return None

    is_bull = gap_pct > 0
    inferred_direction = "BULLISH" if is_bull else "BEARISH"
    # If explicit sector direction_bias is provided and opposes the gap, require a decisive company catalyst gap (>= 2.0%)
    if direction_bias and direction_bias != inferred_direction:
        if abs_gap < 2.0:
            return None

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    direction = "BULLISH" if is_bull else "BEARISH"
    option_type = "CE" if is_bull else "PE"

    from engine.position_sizer import get_lot_size

    lot_sz = get_lot_size(clean_sym)

    from engine.option_resolver import resolve_option_contract

    opt_plan = resolve_option_contract(
        symbol=clean_sym,
        spot=preopen_price,
        direction=direction,
        contracts_override=chain,
    )

    alert_id = generate_alert_id(clean_sym, "PREOPEN_STOCK_CATALYST", variant=direction.lower()[:4])

    headline = f"🌅 [PRE-OPEN CATALYST] {clean_sym} Indicative {gap_pct:+.2f}% Gap in {sector_name or 'Sector'} ({rrg_quadrant or 'RRG'})"
    summary = (
        f"Pre-market price discovery gap: {clean_sym} indicating ₹{preopen_price:,.1f} ({gap_pct:+.2f}% vs prev ₹{prev_close:,.1f}) "
        f"aligned with {direction} sector tailwind in {rrg_quadrant}. Prime order ticket for 09:16 AM confirmation."
    )

    if opt_plan:
        contract_sym = opt_plan.contract_symbol
        entry_prem = opt_plan.entry_premium
        sl_prem = opt_plan.sl_premium
        t1_prem = opt_plan.t1_premium
        strike_val = opt_plan.strike
    else:
        atm_strike = round(preopen_price, 0)
        contract_sym = f"{clean_sym} {format_strike(atm_strike)} {option_type}"
        entry_prem = round(preopen_price * 0.025, 2)
        sl_prem = round(entry_prem * 0.70, 2)
        t1_prem = round(entry_prem * 1.50, 2)
        strike_val = atm_strike

    act_plan = {
        "action": f"STAGE {option_type} TICKET",
        "contract": contract_sym,
        "instrument": contract_sym,
        "instrument_type": "OPTION",
        "strike": strike_val,
        "option_type": option_type,
        "recommended_entry": f"₹{entry_prem:,.2f}",
        "stop_loss": f"₹{sl_prem:,.2f}",
        "target_1": f"₹{t1_prem:,.2f}",
        "underlying_preopen": f"₹{preopen_price:,.1f}",
        "underlying_prev_close": f"₹{prev_close:,.1f}",
        "gap_pct": f"{gap_pct:+.2f}%",
        "sector": sector_name,
        "rrg_quadrant": rrg_quadrant,
        "when_to_buy": "Pre-stage order. Enter strictly after 09:16 AM 1-min candle confirms holding above VWAP.",
        "autoSubmit": False,
        "is_watch_only": False,
        "execution_ready": True,
    }

    return AutoAlert(
        alert_id=alert_id,
        alert_type="PREOPEN_STOCK_CATALYST",
        stage="EARLY_WARNING",
        symbol=clean_sym,
        exchange="NSE",
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=entry_prem,
        trigger_level=entry_prem,
        target_level=t1_prem,
        stop_loss=sl_prem,
        strike=strike_val,
        option_type=option_type,
        contract_symbol=contract_sym,
        option_premium=entry_prem,
        underlying_spot=preopen_price,
        lot_size=lot_sz,
        segment="FNO_STOCK",
        confidence=85,
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        setup_style="CATALYST",
        metrics={
            "preopen_price": preopen_price,
            "prev_close": prev_close,
            "gap_pct": gap_pct,
            "sector": sector_name,
            "rrg_quadrant": rrg_quadrant,
            "direction": direction,
            "lot_size": lot_sz,
        },
        actionable_plan=act_plan,
    )
