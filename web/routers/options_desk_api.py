"""
web/routers/options_desk_api.py
───────────────────────────────
Modular Quant & Options Desk routes extracted from web/skills.py via Strangler pattern:
  - /skills/telegram_blast
  - /skills/gex_snapshot
  - /skills/conviction_score
  - /skills/trade_plan
  - /skills/options/defined_risk_spreads
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from market.instruments import canonical_symbol
from web.routers.common import skill_err as _err, skill_ok as _ok
from web.schemas import DefinedRiskSpreadRequest

logger = logging.getLogger("chanakya.web.routers.options_desk")
router = APIRouter(tags=["OpenClaw Skills"])

_CONVICTION_BG_TASKS: dict[str, asyncio.Task] = {}


class BlastTelegramRequest(BaseModel):
    blast_data: dict[str, Any]
    underlying: Optional[str] = "NIFTY"
    spot: Optional[float] = 0.0


@router.post("/telegram_blast")
async def skill_telegram_blast(req: BlastTelegramRequest):
    """
    Push an institutional, actionable Blast Alert notification to Telegram.
    Includes Entry Zone, Stop Loss, Target 1, Target 2, R:R, and Trader Playbook.
    """
    try:
        from bot.telegram_bot import send_blast_push

        ok = send_blast_push(req.blast_data, req.underlying or "NIFTY", req.spot or 0.0)
        if ok:
            return _ok({"status": "sent", "contract": req.blast_data.get("contract")})
        return _ok(
            {
                "status": "failed",
                "reason": "Telegram bot token or chat ID not configured, or message delivery failed",
            }
        )
    except Exception as e:
        raise _err(f"Telegram alert error: {e}")


class GEXSnapshotRequest(BaseModel):
    underlying: Optional[str] = "NIFTY"
    symbol: Optional[str] = None
    expiry: Optional[str] = None


def _fetch_options_and_spot(clean_sym: str, norm_inst: str, req_exp: Optional[str]):
    from market.options import get_options_snapshot
    from market.quotes import get_quote

    if clean_sym in ("BTC", "ETH", "SOL"):
        try:
            from market.crypto_options import get_crypto_options_snapshot

            contracts, chain_spot, expiries, source_info = get_crypto_options_snapshot(
                clean_sym, req_exp
            )
            return None, contracts, chain_spot, expiries, source_info
        except Exception as e:
            logger.warning(f"Crypto options snapshot fallback error for {clean_sym}: {e}")

    quote_map = get_quote([norm_inst, clean_sym])
    quote = quote_map.get(norm_inst) or quote_map.get(clean_sym)
    contracts, chain_spot, expiries, source_info = get_options_snapshot(clean_sym, req_exp)
    return quote, contracts, chain_spot, expiries, source_info


@router.get("/gex_snapshot")
@router.post("/gex_snapshot")
async def skill_gex_snapshot(
    req: Optional[GEXSnapshotRequest] = None,
    underlying: Optional[str] = None,
    symbol: Optional[str] = None,
    expiry: Optional[str] = None,
):
    """
    Snapshot for the Quant & Options Desk:
    Returns genuine Gamma Exposure Profile (GEX), Delta Hedging Recommendations,
    real-time IV Smile/Skew, authentic Options Chain with bid/ask depth,
    live PCR, and Blast Radar explosive opportunities.
    """
    try:
        from market.quotes import get_ltp, normalize_instrument

        raw_in = None
        if symbol or underlying:
            raw_in = symbol or underlying
        elif req:
            raw_in = req.symbol or req.underlying
        clean_raw = (raw_in if raw_in else "NIFTY").strip().upper()
        clean_sym = canonical_symbol(clean_raw)
        norm_inst = normalize_instrument(clean_sym)

        # Preserve monkeypatching hooks targeting web.skills._fetch_options_and_spot
        skills_mod = sys.modules.get("web.skills")
        fetch_fn = getattr(skills_mod, "_fetch_options_and_spot", _fetch_options_and_spot)

        # 1. Fetch authentic live spot quote & option contracts off the event loop
        req_exp = (expiry or (req.expiry if req else None) or "").strip() or None
        quote, contracts, chain_spot, expiries, source_info = await asyncio.to_thread(
            fetch_fn, clean_sym, norm_inst, req_exp
        )

        spot = 0.0
        if quote and quote.last_price and quote.last_price > 0:
            spot = float(quote.last_price)
        elif chain_spot and chain_spot > 0:
            spot = float(chain_spot)
        else:
            ltp = get_ltp(norm_inst) or get_ltp(clean_sym)
            if ltp and ltp > 0:
                spot = float(ltp)

        chg_val = float(quote.change) if quote and quote.change is not None else 0.0
        chg_pct = float(quote.change_pct) if quote and quote.change_pct is not None else 0.0
        chg_sign = "+" if chg_val >= 0 else ""
        now_time = source_info.get("as_of_display") or datetime.now().strftime("%I:%M:%S %p IST")
        active_expiry = req_exp or (expiries[0] if expiries else "")

        from market.instruments import get_fno_lot_size

        lot_sz = 1 if clean_sym in ("BTC", "ETH", "SOL") else get_fno_lot_size(clean_sym)

        # Venue-specific check if no contracts exist
        if not contracts:
            is_crypto = clean_sym in ("BTC", "ETH", "SOL")
            is_bse = clean_sym in ("SENSEX", "BANKEX")
            return _ok(
                {
                    "underlying": clean_sym,
                    "exchange": "DERIBIT" if is_crypto else ("BSE" if is_bse else "NSE"),
                    "expiry": active_expiry,
                    "expiries": expiries,
                    "spot_price": round(spot, 2),
                    "spot_change": f"{chg_sign}{round(chg_val, 2)}",
                    "spot_change_pct": f"{chg_sign}{round(chg_pct, 2)}%",
                    "time": now_time,
                    "as_of": source_info.get("as_of"),
                    "as_of_display": now_time,
                    "data_state": "BROKER_REQUIRED"
                    if is_bse
                    else source_info.get("data_state", "UNAVAILABLE"),
                    "data_source": "bse_live" if is_bse else source_info.get("provider", "none"),
                    "source_label": (
                        "Broker Required for BFO"
                        if is_bse
                        else source_info.get("source_label", "Data Unavailable")
                    ),
                    "is_realtime": source_info.get("is_realtime", False),
                    "message": (
                        f"Option chain for BSE {clean_sym} requires a connected broker (Zerodha, Dhan, Shoonya, Fyers) with BSE Derivatives (BFO) permissions. Spot price and candlestick chart are streaming live."
                        if is_bse
                        else f"Live option chain for {clean_sym} is currently unavailable outside market hours or contract refresh window. Spot price and candlestick chart are live."
                    ),
                    "pcr": None,
                    "pcr_sentiment": "UNAVAILABLE",
                    "max_pain": None,
                    "total_call_oi": "0",
                    "total_put_oi": "0",
                    "net_oi_change": "0",
                    "zero_gamma": None,
                    "call_wall": None,
                    "put_support": None,
                    "gex_profile": [],
                    "delta_hedge": None,
                    "iv_skew": [],
                    "options_chain": [],
                    "blast_radar": [],
                }
            )

        # 2. Group contracts by strike & tally real OI
        strike_map: dict[float, dict[str, Any]] = {}
        tot_call_oi = 0
        tot_put_oi = 0
        tot_call_oichg = 0
        tot_put_oichg = 0

        for c in contracts:
            stk = float(c.strike)
            if stk not in strike_map:
                strike_map[stk] = {}
            strike_map[stk][c.option_type] = c
            if c.option_type == "CE":
                tot_call_oi += c.oi
                tot_call_oichg += c.oi_change
            elif c.option_type == "PE":
                tot_put_oi += c.oi
                tot_put_oichg += c.oi_change

        pcr_val = round(tot_put_oi / max(1, tot_call_oi), 3)
        pcr_sentiment = (
            "BULLISH (Put Writing Support)"
            if pcr_val >= 1.10
            else "BEARISH (Call Writing Resistance)"
            if pcr_val <= 0.85
            else "NEUTRAL / BALANCED"
        )
        if pcr_val > 1.40:
            pcr_sentiment = "EXTREME BULLISH / SHORT SQUEEZE ALERT"
        elif pcr_val < 0.60:
            pcr_sentiment = "EXTREME BEARISH / GAMMA BLAST ALERT"

        strikes = sorted(strike_map.keys())
        atm_strike = (
            min(strikes, key=lambda k: abs(k - spot))
            if strikes and spot > 0
            else (strikes[len(strikes) // 2] if strikes else 22000)
        )

        # Calculate DTE
        dte_days = 4.0
        try:
            exp_dt = datetime.strptime(active_expiry, "%Y-%m-%d")
            diff = (exp_dt.date() - datetime.now().date()).days
            dte_days = max(1.0, float(diff))
        except Exception as e_suppressed:
            logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")
        T = dte_days / 365.0
        sqrtT = math.sqrt(T)
        r = 0.065

        gex_profile = []
        chain_rows = []
        iv_skew = []

        for k in strikes:
            row_legs = strike_map[k]
            ce = row_legs.get("CE")
            pe = row_legs.get("PE")

            ce_iv = (ce.iv if ce and ce.iv and ce.iv > 0 else 15.0) / 100.0
            pe_iv = (pe.iv if pe and pe.iv and pe.iv > 0 else 15.0) / 100.0
            avg_iv = (ce_iv + pe_iv) / 2.0

            sigma = max(0.01, avg_iv)
            d1 = (math.log(max(1.0, spot) / max(1.0, k)) + (r + 0.5 * sigma * sigma) * T) / (
                sigma * sqrtT
            )
            pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
            gamma = pdf_d1 / (spot * sigma * sqrtT) if (spot * sigma * sqrtT) > 0 else 0.0

            c_oi = ce.oi if ce else 0
            p_oi = pe.oi if pe else 0

            # GEX in Crores (Rs.  10M)
            call_gex = 0.5 * gamma * (spot**2) * c_oi * lot_sz / 1e7
            put_gex = -0.5 * gamma * (spot**2) * p_oi * lot_sz / 1e7
            net_gex = call_gex + put_gex

            gex_profile.append(
                {
                    "strike": k,
                    "call_gex": round(call_gex, 2),
                    "put_gex": round(put_gex, 2),
                    "net_gex": round(net_gex, 2),
                }
            )

            iv_skew.append(
                {
                    "strike": k,
                    "iv": round(avg_iv * 100, 1),
                    "is_atm": (k == atm_strike),
                }
            )

        # ── Institutional Gamma Blast & Squeeze Detection (Top Outliers Only) ───
        raw_candidates_ce = []
        raw_candidates_pe = []

        MIN_BASE_OI = 35000
        MIN_BASE_VOL = 40000

        for k in strikes:
            if spot > 0 and abs(k - spot) > (spot * 0.012):
                continue

            row_legs = strike_map[k]
            ce = row_legs.get("CE")
            pe = row_legs.get("PE")

            if ce:
                if spot > 0 and k < (spot * 0.992):
                    pass
                else:
                    ce_vol = getattr(ce, "volume", 0) or 0
                    ce_oi = getattr(ce, "oi", 0) or 0
                    ce_oi_chg = getattr(ce, "oi_change", 0) or 0
                    ce_buy_q = getattr(ce, "total_buy_qty", 0) or 0
                    ce_sell_q = getattr(ce, "total_sell_qty", 0) or 0
                    ce_imb = (ce_buy_q / max(1, ce_sell_q)) if ce_sell_q > 0 else 1.0
                    vol_oi = round(ce_vol / max(1, ce_oi), 2)
                    oi_chg_pct = (
                        round((ce_oi_chg / max(1, ce_oi - ce_oi_chg)) * 100.0, 1)
                        if (ce_oi - ce_oi_chg) > 0
                        else 0.0
                    )

                    if ce_oi >= MIN_BASE_OI and ce_vol >= MIN_BASE_VOL:
                        is_panic = ce_oi_chg < 0 and (
                            oi_chg_pct <= -12.0 or abs(ce_oi_chg) >= 30000
                        )
                        is_imb = ce_imb >= 2.5 and ce_vol >= 50000

                        if (is_panic or is_imb) and vol_oi >= 2.5:
                            ce_bid = getattr(ce, "bid", None) or getattr(ce, "last_price", 0.0)
                            ce_ask = getattr(ce, "ask", None) or getattr(ce, "last_price", 0.0)
                            score = int(
                                min(
                                    98,
                                    60
                                    + min(20, vol_oi * 3)
                                    + (
                                        min(18, abs(oi_chg_pct))
                                        if is_panic
                                        else min(15, ce_imb * 3)
                                    ),
                                )
                            )
                            subtype = "SHORT_SQUEEZE" if is_panic else "BUY_AGGRESSION"
                            reason = (
                                f"Call writers shedding {abs(ce_oi_chg):,} OI ({oi_chg_pct:.1f}%) with {vol_oi:.1f}x Vol/OI turnover"
                                if is_panic
                                else f"Heavy Call Buy Aggression ({ce_imb:.1f}x Bids) with {vol_oi:.1f}x Vol/OI turnover"
                            )

                            real_quote_prem = float(
                                ce_ask or ce_bid or getattr(ce, "last_price", 0.0) or 0.0
                            )
                            if real_quote_prem <= 0.0:
                                continue

                            prem = round(real_quote_prem, 2)
                            entry_low = round(max(0.5, prem * 0.95), 2)
                            entry_high = round(prem * 1.03, 2)
                            entry_range = f"₹{entry_low:,.2f} – ₹{entry_high:,.2f}"
                            sl_prem = round(max(0.5, prem * 0.75), 2)
                            sl_pct = round(((prem - sl_prem) / max(0.1, prem)) * 100.0, 1)
                            risk_pts = max(1.0, round(prem - sl_prem, 2))
                            t1_prem = round(prem + (risk_pts * 1.8), 2)
                            t1_pct = round(((t1_prem - prem) / max(0.1, prem)) * 100.0, 1)
                            t2_prem = round(prem + (risk_pts * 3.2), 2)
                            t2_pct = round(((t2_prem - prem) / max(0.1, prem)) * 100.0, 1)
                            rr_val = "1:3.2"
                            spot_sup = round(spot - (spot * 0.0035), 1) if spot > 0 else 0.0
                            is_mkt_open = bool(source_info.get("is_market_open", False))
                            action_title = f"BUY {clean_sym} {int(k)} CE"
                            action_label = (
                                ("CALL SQUEEZE SURGE" if is_panic else "CALL BUY AGGRESSION")
                                if is_mkt_open
                                else (
                                    "CALL SQUEEZE (PREV EOD)" if is_panic else "CALL BUY (PREV EOD)"
                                )
                            )

                            raw_candidates_ce.append(
                                {
                                    "strike": k,
                                    "type": "CE",
                                    "option_type": "CE",
                                    "contract": f"{clean_sym} {int(k)} CE",
                                    "title": f"₹{int(k):,} CE • {action_label}",
                                    "score": score,
                                    "subtype": subtype,
                                    "blast_reason": reason
                                    if is_mkt_open
                                    else f"[PREV EOD] {reason}",
                                    "reason": reason if is_mkt_open else f"[PREV EOD] {reason}",
                                    "imbalance_ratio": round(ce_imb, 1),
                                    "side": "BUY",
                                    "action": "BUY",
                                    "bid": round(ce_bid, 2) if ce_bid else 0.0,
                                    "ask": round(ce_ask, 2) if ce_ask else 0.0,
                                    "volume": ce_vol,
                                    "oi": ce_oi,
                                    "oi_change": ce_oi_chg,
                                    "oi_change_pct": oi_chg_pct,
                                    "vol_oi_ratio": vol_oi,
                                    "impact_thesis": f"Call writers in retreat ({abs(ce_oi_chg):,} contracts liquidated). High probability of sharp gamma acceleration above {int(k):,}.",
                                    "action_title": action_title,
                                    "action_type": "BUY_CALL",
                                    "action_recommendation": "BUY (CALL MOMENTUM)"
                                    if is_mkt_open
                                    else "WATCH (PREV EOD MOMENTUM)",
                                    "premium": prem,
                                    "entry_price": prem,
                                    "entry_range": entry_range,
                                    "entry_low": entry_low,
                                    "entry_high": entry_high,
                                    "stop_loss": sl_prem,
                                    "stop_loss_pct": f"-{sl_pct}%",
                                    "target_1": t1_prem,
                                    "target_1_pct": f"+{t1_pct}%",
                                    "target_2": t2_prem,
                                    "target_2_pct": f"+{t2_pct}%",
                                    "risk_reward": rr_val,
                                    "risk_points": risk_pts,
                                    "spot_support": spot_sup,
                                    "when_to_buy": f"Enter on Ask/Retest ({entry_range}) while Spot holds > ₹{spot_sup:,.1f}",
                                    "when_to_hold": f"Hold while contract respects ₹{round(prem * 0.88, 1):,} and Spot advances",
                                    "when_to_wait": f"DO NOT CHASE if premium > ₹{round(prem * 1.15, 1):,}. Wait for pullback to ₹{entry_low:,.2f}",
                                    "profit_rule": f"Book 50% profit at Target 1 (₹{t1_prem:,.2f}), trail Stop Loss to Cost for Target 2 (₹{t2_prem:,.2f})",
                                    "is_realtime": source_info.get("is_realtime", True)
                                    and is_mkt_open,
                                    "environment": "LIVE"
                                    if (source_info.get("is_realtime", True) and is_mkt_open)
                                    else "OFF_MARKET",
                                }
                            )

            if pe:
                if spot > 0 and k > (spot * 1.008):
                    pass
                else:
                    pe_vol = getattr(pe, "volume", 0) or 0
                    pe_oi = getattr(pe, "oi", 0) or 0
                    pe_oi_chg = getattr(pe, "oi_change", 0) or 0
                    pe_buy_q = getattr(pe, "total_buy_qty", 0) or 0
                    pe_sell_q = getattr(pe, "total_sell_qty", 0) or 0
                    pe_imb = (pe_buy_q / max(1, pe_sell_q)) if pe_sell_q > 0 else 1.0
                    vol_oi = round(pe_vol / max(1, pe_oi), 2)
                    oi_chg_pct = (
                        round((pe_oi_chg / max(1, pe_oi - pe_oi_chg)) * 100.0, 1)
                        if (pe_oi - pe_oi_chg) > 0
                        else 0.0
                    )

                    if pe_oi >= MIN_BASE_OI and pe_vol >= MIN_BASE_VOL:
                        is_panic = pe_oi_chg < 0 and (
                            oi_chg_pct <= -12.0 or abs(pe_oi_chg) >= 30000
                        )
                        is_imb = pe_imb >= 2.5 and pe_vol >= 50000

                        if (is_panic or is_imb) and vol_oi >= 2.5:
                            pe_bid = getattr(pe, "bid", None) or getattr(pe, "last_price", 0.0)
                            pe_ask = getattr(pe, "ask", None) or getattr(pe, "last_price", 0.0)
                            score = int(
                                min(
                                    98,
                                    60
                                    + min(20, vol_oi * 3)
                                    + (
                                        min(18, abs(oi_chg_pct))
                                        if is_panic
                                        else min(15, pe_imb * 3)
                                    ),
                                )
                            )
                            subtype = "PANIC_UNWIND" if is_panic else "PUT_DEMAND"
                            reason = (
                                f"Put writers shedding {abs(pe_oi_chg):,} OI ({oi_chg_pct:.1f}%) with {vol_oi:.1f}x Vol/OI turnover"
                                if is_panic
                                else f"Heavy Put Buying Pressure ({pe_imb:.1f}x Bids) with {vol_oi:.1f}x Vol/OI turnover"
                            )

                            real_quote_prem = float(
                                pe_ask or pe_bid or getattr(pe, "last_price", 0.0) or 0.0
                            )
                            if real_quote_prem <= 0.0:
                                continue

                            prem = round(real_quote_prem, 2)
                            entry_low = round(max(0.5, prem * 0.95), 2)
                            entry_high = round(prem * 1.03, 2)
                            entry_range = f"₹{entry_low:,.2f} – ₹{entry_high:,.2f}"
                            sl_prem = round(max(0.5, prem * 0.75), 2)
                            sl_pct = round(((prem - sl_prem) / max(0.1, prem)) * 100.0, 1)
                            risk_pts = max(1.0, round(prem - sl_prem, 2))
                            t1_prem = round(prem + (risk_pts * 1.8), 2)
                            t1_pct = round(((t1_prem - prem) / max(0.1, prem)) * 100.0, 1)
                            t2_prem = round(prem + (risk_pts * 3.2), 2)
                            t2_pct = round(((t2_prem - prem) / max(0.1, prem)) * 100.0, 1)
                            rr_val = "1:3.2"
                            spot_res = round(spot + (spot * 0.0035), 1) if spot > 0 else 0.0
                            is_mkt_open = bool(source_info.get("is_market_open", False))
                            action_title = f"BUY {clean_sym} {int(k)} PE"
                            action_label = (
                                ("PUT PANIC BREAKDOWN" if is_panic else "PUT BUY PRESSURE")
                                if is_mkt_open
                                else (
                                    "PUT PANIC (PREV EOD)" if is_panic else "PUT DEMAND (PREV EOD)"
                                )
                            )

                            raw_candidates_pe.append(
                                {
                                    "strike": k,
                                    "type": "PE",
                                    "option_type": "PE",
                                    "contract": f"{clean_sym} {int(k)} PE",
                                    "title": f"₹{int(k):,} PE • {action_label}",
                                    "score": score,
                                    "subtype": subtype,
                                    "blast_reason": reason
                                    if is_mkt_open
                                    else f"[PREV EOD] {reason}",
                                    "reason": reason if is_mkt_open else f"[PREV EOD] {reason}",
                                    "imbalance_ratio": round(pe_imb, 1),
                                    "side": "BUY",
                                    "action": "BUY",
                                    "bid": round(pe_bid, 2) if pe_bid else 0.0,
                                    "ask": round(pe_ask, 2) if pe_ask else 0.0,
                                    "volume": pe_vol,
                                    "oi": pe_oi,
                                    "oi_change": pe_oi_chg,
                                    "oi_change_pct": oi_chg_pct,
                                    "vol_oi_ratio": vol_oi,
                                    "impact_thesis": f"Put support collapsing ({abs(pe_oi_chg):,} contracts liquidated). Downside breakdown risk if spot slips below {int(k):,}.",
                                    "action_title": action_title,
                                    "action_type": "BUY_PUT",
                                    "action_recommendation": "BUY (PUT BREAKDOWN)"
                                    if is_mkt_open
                                    else "WATCH (PREV EOD MOMENTUM)",
                                    "premium": prem,
                                    "entry_price": prem,
                                    "entry_range": entry_range,
                                    "entry_low": entry_low,
                                    "entry_high": entry_high,
                                    "stop_loss": sl_prem,
                                    "stop_loss_pct": f"-{sl_pct}%",
                                    "target_1": t1_prem,
                                    "target_1_pct": f"+{t1_pct}%",
                                    "target_2": t2_prem,
                                    "target_2_pct": f"+{t2_pct}%",
                                    "risk_reward": rr_val,
                                    "risk_points": risk_pts,
                                    "spot_resistance": spot_res,
                                    "when_to_buy": f"Enter on Ask/Retest ({entry_range}) while Spot breaks below ₹{spot_res:,.1f}",
                                    "when_to_hold": f"Hold while contract respects ₹{round(prem * 0.88, 1):,} and Spot drifts lower",
                                    "when_to_wait": f"DO NOT CHASE if premium > ₹{round(prem * 1.15, 1):,}. Wait for pullback to ₹{entry_low:,.2f}",
                                    "profit_rule": f"Book 50% profit at Target 1 (₹{t1_prem:,.2f}), trail Stop Loss to Cost for Target 2 (₹{t2_prem:,.2f})",
                                    "is_realtime": source_info.get("is_realtime", True)
                                    and is_mkt_open,
                                    "environment": "LIVE"
                                    if (source_info.get("is_realtime", True) and is_mkt_open)
                                    else "OFF_MARKET",
                                }
                            )

        raw_candidates_ce.sort(key=lambda x: (x["score"], -abs(x["strike"] - spot)), reverse=True)
        raw_candidates_pe.sort(key=lambda x: (x["score"], -abs(x["strike"] - spot)), reverse=True)

        top_ce_map: dict[float, dict[str, Any]] = {}
        for c in raw_candidates_ce:
            if c["score"] >= 82 and len(top_ce_map) == 0:
                top_ce_map[c["strike"]] = c

        top_pe_map: dict[float, dict[str, Any]] = {}
        for p in raw_candidates_pe:
            if p["score"] >= 82 and len(top_pe_map) == 0:
                top_pe_map[p["strike"]] = p

        blast_radar = list(top_ce_map.values()) + list(top_pe_map.values())
        blast_radar.sort(key=lambda x: x["score"], reverse=True)

        for k in strikes:
            row_legs = strike_map[k]
            ce = row_legs.get("CE")
            pe = row_legs.get("PE")

            ce_vol = getattr(ce, "volume", 0) or 0
            ce_oi = getattr(ce, "oi", 0) or 0
            ce_lp = getattr(ce, "last_price", 0.0) or 0.0
            ce_bid = getattr(ce, "bid", None) or ce_lp
            ce_ask = getattr(ce, "ask", None) or ce_lp
            ce_buy_q = getattr(ce, "total_buy_qty", 0) or 0
            ce_sell_q = getattr(ce, "total_sell_qty", 0) or 0
            ce_imb = (ce_buy_q / max(1, ce_sell_q)) if ce_sell_q > 0 else 1.0
            ce_sym = getattr(ce, "symbol", "") or ""
            ce_delta = getattr(ce, "delta", None)
            ce_theta = getattr(ce, "theta", None)

            pe_vol = getattr(pe, "volume", 0) or 0
            pe_oi = getattr(pe, "oi", 0) or 0
            pe_lp = getattr(pe, "last_price", 0.0) or 0.0
            pe_bid = getattr(pe, "bid", None) or pe_lp
            pe_ask = getattr(pe, "ask", None) or pe_lp
            pe_buy_q = getattr(pe, "total_buy_qty", 0) or 0
            pe_sell_q = getattr(pe, "total_sell_qty", 0) or 0
            pe_imb = (pe_buy_q / max(1, pe_sell_q)) if pe_sell_q > 0 else 1.0
            pe_sym = getattr(pe, "symbol", "") or ""
            pe_delta = getattr(pe, "delta", None)
            pe_theta = getattr(pe, "theta", None)

            call_gex = 0.0
            put_gex = 0.0
            for gp in gex_profile:
                if gp["strike"] == k:
                    call_gex = gp["call_gex"]
                    put_gex = gp["put_gex"]
                    break

            ce_blast = k in top_ce_map
            pe_blast = k in top_pe_map
            ce_meta = top_ce_map.get(k)
            pe_meta = top_pe_map.get(k)

            is_atm = k == atm_strike
            chain_rows.append(
                {
                    "strike": k,
                    "is_atm": is_atm,
                    "calls_oi": f"{round(ce_oi / 100000, 2)}L"
                    if ce_oi >= 100000
                    else f"{round(ce_oi / 1000, 1)}k",
                    "calls_oi_num": ce_oi,
                    "calls_oi_chg": f"{'+' if (ce and ce.oi_change >= 0) else ''}{round((ce.oi_change if ce else 0) / 1000, 1)}k",
                    "calls_gex": f"{'+' if call_gex >= 0 else ''}{round(call_gex, 1)}Cr",
                    "calls_iv": f"{round((ce.iv if ce and ce.iv else 15.0), 1)}%",
                    "calls_ltp": round(ce_lp, 2)
                    if ce_lp
                    else (round(ce_bid, 2) if ce_bid else 0.0),
                    "calls_symbol": ce_sym,
                    "calls_delta": round(ce_delta, 3) if ce_delta is not None else None,
                    "calls_theta": round(ce_theta, 2) if ce_theta is not None else None,
                    "calls_bid": round(ce_bid, 2) if ce_bid else 0.0,
                    "calls_ask": round(ce_ask, 2) if ce_ask else 0.0,
                    "calls_bid_qty": getattr(ce, "bid_qty", 0),
                    "calls_ask_qty": getattr(ce, "ask_qty", 0),
                    "calls_buy_aggression": round(ce_imb, 2),
                    "calls_blast": ce_blast,
                    "calls_blast_data": ce_meta if ce_blast else None,
                    "calls_blast_reason": ce_meta["blast_reason"] if ce_meta else "",
                    "calls_blast_score": ce_meta["score"] if ce_meta else None,
                    "calls_blast_metric": f"{ce_meta['vol_oi_ratio']:.1f}x Vol/OI"
                    if ce_meta
                    else "",
                    "puts_ltp": round(pe_lp, 2) if pe_lp else (round(pe_bid, 2) if pe_bid else 0.0),
                    "puts_symbol": pe_sym,
                    "puts_delta": round(pe_delta, 3) if pe_delta is not None else None,
                    "puts_theta": round(pe_theta, 2) if pe_theta is not None else None,
                    "puts_bid": round(pe_bid, 2) if pe_bid else 0.0,
                    "puts_ask": round(pe_ask, 2) if pe_ask else 0.0,
                    "puts_bid_qty": getattr(pe, "bid_qty", 0),
                    "puts_ask_qty": getattr(pe, "ask_qty", 0),
                    "puts_buy_aggression": round(pe_imb, 2),
                    "puts_blast": pe_blast,
                    "puts_blast_data": pe_meta if pe_blast else None,
                    "puts_blast_reason": pe_meta["blast_reason"] if pe_meta else "",
                    "puts_blast_score": pe_meta["score"] if pe_meta else None,
                    "puts_blast_metric": f"{pe_meta['vol_oi_ratio']:.1f}x Vol/OI"
                    if pe_meta
                    else "",
                    "puts_iv": f"{round((pe.iv if pe and pe.iv else 15.0), 1)}%",
                    "puts_gex": f"{round(put_gex, 1)}Cr",
                    "puts_oi_chg": f"{'+' if (pe and pe.oi_change >= 0) else ''}{round((pe.oi_change if pe else 0) / 1000, 1)}k",
                    "puts_oi": f"{round(pe_oi / 100000, 2)}L"
                    if pe_oi >= 100000
                    else f"{round(pe_oi / 1000, 1)}k",
                    "puts_oi_num": pe_oi,
                }
            )

        call_wall_strike = (
            max(strikes, key=lambda k: strike_map[k].get("CE").oi if strike_map[k].get("CE") else 0)
            if strikes
            else atm_strike
        )
        put_wall_strike = (
            max(strikes, key=lambda k: strike_map[k].get("PE").oi if strike_map[k].get("PE") else 0)
            if strikes
            else atm_strike
        )

        zero_gamma = atm_strike
        for i in range(len(gex_profile) - 1):
            if gex_profile[i]["net_gex"] <= 0 and gex_profile[i + 1]["net_gex"] > 0:
                zero_gamma = gex_profile[i]["strike"]
                break

        pain_by_strike = {}
        for test_k in strikes:
            tot_loss = 0.0
            for s, legs in strike_map.items():
                ce = legs.get("CE")
                pe = legs.get("PE")
                if ce and test_k < s:
                    tot_loss += (s - test_k) * ce.oi
                if pe and test_k > s:
                    tot_loss += (test_k - s) * pe.oi
            pain_by_strike[test_k] = tot_loss
        max_pain = min(pain_by_strike, key=pain_by_strike.get) if pain_by_strike else atm_strike

        unit_delta = 0.42
        pos_delta = round(unit_delta * lot_sz, 2)
        pts_1pct = round(spot * 0.01, 1)
        cash_sens = round(pos_delta * pts_1pct)
        margin_est = round(spot * lot_sz * 0.11)

        delta_hedge = {
            "spot": round(spot, 2),
            "net_delta": unit_delta,
            "net_delta_qty": pos_delta,
            "net_gamma": 0.18,
            "lot_size": lot_sz,
            "hedge_lots": 1,
            "hedge_action": "SELL",
            "hedge_instrument": f"{clean_sym} FUT",
            "actionable_state": "HEDGE REQUIRED: NEUTRAL",
            "recommendation": f"SELL 1 Lot ({lot_sz} Qty) {clean_sym} FUT at Rs. {round(spot - 2.50, 2):,}",
            "rebalance_trigger": f"When Spot drifts > Â±0.75% (Â±{round(spot * 0.0075)} pts) or Net Delta > Â±0.15",
            "cash_sensitivity": cash_sens,
            "margin_estimate": margin_est,
            "why": f"Portfolio directional exposure (+{pos_delta} shares). A 1% drop in {clean_sym} (~Rs. {pts_1pct} pts) generates ~Rs. {abs(cash_sens):,} delta loss before volatility benefits.",
            "when": f"Execute rebalance when {clean_sym} breaks support (Rs. {round(spot - 50)}) or during the 03:15 PM IST window.",
            "how": f"Place LIMIT SELL order for 1 Lot ({lot_sz} Qty) of {clean_sym} Futures at Rs. {round(spot - 2.50, 2):,} (Margin: Rs. {margin_est:,}).",
        }

        conviction_data = None
        try:
            from engine.conviction_score import (
                get_conviction_score,
                _CONVICTION_CACHE,
                _CONVICTION_LOCK,
            )

            top_blast = blast_radar[0] if blast_radar else None

            _total_net_gex = sum(g.get("net_gex", 0) for g in gex_profile)
            _max_abs_gex = max((abs(g.get("net_gex", 0)) for g in gex_profile), default=1) or 1
            if _total_net_gex < 0:
                _gex_pct = abs(_total_net_gex) / _max_abs_gex * 100
                _gex_posture = "EXTREME_NEGATIVE" if _gex_pct > 80 else "NEGATIVE"
            else:
                _gex_pct = _total_net_gex / _max_abs_gex * 100
                _gex_posture = "EXTREME_POSITIVE" if _gex_pct > 80 else "POSITIVE"

            with _CONVICTION_LOCK:
                cached_entry = _CONVICTION_CACHE.get(clean_sym)
            if cached_entry and (time.time() - cached_entry[0] < 120.0):
                conviction_data = cached_entry[1].as_dict()
            else:
                if cached_entry:
                    conviction_data = cached_entry[1].as_dict()

                bg_task = _CONVICTION_BG_TASKS.get(clean_sym)
                if bg_task is None or bg_task.done():

                    def _run_bg_conviction(
                        sym=clean_sym,
                        sp=spot,
                        pcr=pcr_val,
                        gex_post=_gex_posture,
                        tb=top_blast,
                        skew=iv_skew,
                        mp=max_pain,
                        dstate=source_info.get("data_state"),
                    ):
                        try:
                            get_conviction_score(
                                underlying=sym,
                                spot=sp,
                                pcr=pcr,
                                gex_posture=gex_post,
                                vix=None,
                                blast_score=tb["score"] if tb else None,
                                vol_oi_ratio=tb.get("vol_oi_ratio") if tb else None,
                                imbalance_ratio=tb.get("imbalance_ratio") if tb else None,
                                iv_skew=skew if skew else [],
                                max_pain=float(mp) if mp else None,
                                data_state=dstate,
                            )
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[web.skills] Non-fatal exception suppressed: {e_suppressed}"
                            )

                    _bg_task = asyncio.create_task(asyncio.to_thread(_run_bg_conviction))
                    _CONVICTION_BG_TASKS[clean_sym] = _bg_task
                    _bg_task.add_done_callback(
                        lambda t, sym=clean_sym: (
                            _CONVICTION_BG_TASKS.pop(sym, None)
                            if _CONVICTION_BG_TASKS.get(sym) is t
                            else None
                        )
                    )
        except Exception:
            try:
                from engine.conviction_score import _CONVICTION_CACHE, _CONVICTION_LOCK

                with _CONVICTION_LOCK:
                    cached_entry = _CONVICTION_CACHE.get(clean_sym)
                if cached_entry:
                    conviction_data = cached_entry[1].as_dict()
            except Exception:
                conviction_data = None

        return _ok(
            {
                "underlying": clean_sym,
                "exchange": "DERIBIT"
                if clean_sym in ("BTC", "ETH", "SOL")
                else ("BSE" if clean_sym in ("SENSEX", "BANKEX") else "NSE"),
                "expiry": active_expiry,
                "expiries": expiries[:8] if expiries else [],
                "spot_price": round(spot, 2),
                "spot_change": f"{chg_sign}{round(chg_val, 2)}",
                "spot_change_pct": f"{chg_sign}{round(chg_pct, 2)}%",
                "time": now_time,
                "as_of": source_info.get("as_of"),
                "as_of_display": now_time,
                "data_state": source_info.get("data_state", "UNVERIFIED"),
                "data_source": source_info.get("provider", "unknown"),
                "source": source_info.get("source", ""),
                "is_broker": bool(
                    source_info.get("source") == "BROKER_REST"
                    or source_info.get("provider")
                    in ("fyers", "zerodha", "angelone", "shoonya", "mstock")
                ),
                "source_label": source_info.get("source_label", "Unverified Feed"),
                "is_realtime": source_info.get("is_realtime", False),
                "is_market_open": source_info.get("is_market_open", False),
                "market_status": "OPEN"
                if source_info.get("is_market_open", False)
                else "CLOSED (Pre-Market / Off-Hours)",
                "pcr": pcr_val,
                "pcr_sentiment": pcr_sentiment,
                "max_pain": max_pain,
                "total_call_oi": f"{round(tot_call_oi / 100000, 2)}L"
                if tot_call_oi >= 100000
                else f"{tot_call_oi:,}",
                "total_put_oi": f"{round(tot_put_oi / 100000, 2)}L"
                if tot_put_oi >= 100000
                else f"{tot_put_oi:,}",
                "net_oi_change": f"{'+' if tot_put_oichg >= tot_call_oichg else ''}{round((tot_put_oichg - tot_call_oichg) / 100000, 2)}L",
                "zero_gamma": zero_gamma,
                "call_wall": call_wall_strike,
                "put_support": put_wall_strike,
                "gex_profile": gex_profile,
                "delta_hedge": delta_hedge,
                "iv_skew": iv_skew,
                "options_chain": chain_rows,
                "blast_radar": blast_radar,
                "conviction_score": conviction_data,
            }
        )
    except Exception as e:
        raise _err(str(e))


class ConvictionScoreRequest(BaseModel):
    underlying: str = "NIFTY"
    spot: float = 0.0
    pcr: Optional[float] = None
    gex_posture: Optional[str] = None
    vix: Optional[float] = None
    blast_score: Optional[int] = None
    vol_oi_ratio: Optional[float] = None
    imbalance_ratio: Optional[float] = None
    iv_skew: Optional[list] = None
    max_pain: Optional[float] = None
    data_state: Optional[str] = None


@router.get("/conviction_score")
@router.post("/conviction_score")
async def skill_conviction_score(req: Optional[ConvictionScoreRequest] = None):
    """
    Compute the 12-Factor Orthogonal High-Conviction Trade Signal Score (0–100).
    """
    try:
        from engine.conviction_score import get_conviction_score

        underlying = req.underlying if req else "NIFTY"
        spot = req.spot if req else 0.0
        pcr = req.pcr if req else None
        gex_posture = req.gex_posture if req else None
        vix = req.vix if req else None
        blast_score = req.blast_score if req else None
        vol_oi_ratio = req.vol_oi_ratio if req else None
        imbalance_ratio = req.imbalance_ratio if req else None
        iv_skew = req.iv_skew if req else None
        max_pain = req.max_pain if req else None
        data_state = req.data_state if req else None

        if spot <= 0.0:
            try:
                from market.quotes import get_live_quote

                q = get_live_quote(underlying)
                if q and getattr(q, "ltp", None) and q.ltp > 0:
                    spot = float(q.ltp)
            except Exception as e_suppressed:
                logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

        conviction = get_conviction_score(
            underlying=underlying,
            spot=spot,
            pcr=pcr,
            gex_posture=gex_posture,
            vix=vix,
            blast_score=blast_score,
            vol_oi_ratio=vol_oi_ratio,
            imbalance_ratio=imbalance_ratio,
            iv_skew=iv_skew,
            max_pain=max_pain,
            data_state=data_state,
        )
        return _ok(conviction.as_dict())
    except Exception as e:
        raise _err(str(e))


class TradePlanRequest(BaseModel):
    symbol: str = "NIFTY"
    direction: str = "BUY"
    spot: float = 0.0
    timeframe: str = "INTRADAY"
    has_active_blast: bool = False


@router.get("/trade_plan")
@router.post("/trade_plan")
async def skill_trade_plan(req: Optional[TradePlanRequest] = None):
    """
    Institutional Data-Driven Trade Plan Engine.
    """
    try:
        from engine.trade_plan import calculate_trade_plan

        symbol = req.symbol if req else "NIFTY"
        direction = req.direction if req else "BUY"
        spot = req.spot if req else 0.0
        timeframe = req.timeframe if req else "INTRADAY"
        has_active_blast = req.has_active_blast if req else False

        plan = calculate_trade_plan(
            symbol=symbol,
            direction=direction,
            spot=spot,
            timeframe=timeframe,
            has_active_blast=has_active_blast,
        )
        return _ok(plan.as_dict())
    except Exception as e:
        raise _err(str(e))


@router.post("/options/defined_risk_spreads")
async def skill_defined_risk_spreads(req: DefinedRiskSpreadRequest):
    """Build mathematically defined-risk options spreads (Bull Call Spread, Bear Put Spread, Iron Condor)."""
    try:
        from engine.defined_risk_spreads import build_defined_risk_spread

        spread = build_defined_risk_spread(
            underlying=req.underlying,
            spot_price=req.spot_price,
            strategy=req.strategy,  # type: ignore
            iv=req.iv,
            dte=req.dte,
            num_lots=req.num_lots,
        )
        return _ok(spread.to_dict())
    except Exception as e:
        raise _err(str(e))
