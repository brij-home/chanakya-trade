from __future__ import annotations
import logging, os, uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo
from engine.alert_model import AutoAlert
from engine.alert_expiry import classify_expiry_type

logger = logging.getLogger(__name__)
IST = ZoneInfo('Asia/Kolkata')
_BIAS_THRESHOLD_PCT = 0.30
_STRONG_BIAS_PCT = 0.60
_INDEX_UNIVERSE = frozenset({'NIFTY', 'BANKNIFTY'})

def detect_preopen_bias(underlying, gift_futures_price, prev_close, chain, atm_ce_ltp=None, atm_pe_ltp=None, atm_strike=None):
    clean_sym = underlying.upper().replace('.NS', '').replace('NSE:', '').strip()
    if clean_sym not in _INDEX_UNIVERSE:
        return []
    if gift_futures_price <= 0 or prev_close <= 0:
        return []
    now_dt = datetime.now(IST)
    is_preopen = (now_dt.hour == 9 and 5 <= now_dt.minute <= 14)
    is_test = os.environ.get('CHANAKYA_TESTING') == '1' or 'PYTEST_CURRENT_TEST' in os.environ
    if not is_preopen and not is_test:
        return []
    gap_pct = (gift_futures_price - prev_close) / prev_close * 100.0
    abs_gap = abs(gap_pct)
    if abs_gap < _BIAS_THRESHOLD_PCT:
        return []
    is_bullish = gap_pct > 0
    signal_type = 'PREOPEN_CALL_BIAS' if is_bullish else 'PREOPEN_PUT_BIAS'
    option_type = 'CE' if is_bullish else 'PE'
    direction = 'BULLISH' if is_bullish else 'BEARISH'
    strength = 'STRONG' if abs_gap >= _STRONG_BIAS_PCT else 'MODERATE'
    confidence = min(88, 72 + (10 if abs_gap >= _STRONG_BIAS_PCT else 0))
    if atm_strike is None or atm_strike <= 0:
        step = 100.0 if clean_sym == 'BANKNIFTY' else 50.0
        atm_strike = round(gift_futures_price / step) * step
    chosen_ltp = (atm_ce_ltp if is_bullish else atm_pe_ltp) or 0.0
    if chosen_ltp <= 0 and chain:
        cands = [c for c in chain if getattr(c, 'option_type', '') == option_type and abs(getattr(c, 'strike', 0) - atm_strike) <= (100 if clean_sym == 'BANKNIFTY' else 50) and getattr(c, 'last_price', 0) > 0]
        if cands:
            cands.sort(key=lambda c: abs(getattr(c, 'strike', 0) - atm_strike))
            chosen_ltp = float(getattr(cands[0], 'last_price', 0))
            atm_strike = float(getattr(cands[0], 'strike', atm_strike))
    exp_date = None
    exp_type = 'WEEKLY'
    if chain:
        wc = sorted([c for c in chain if getattr(c, 'option_type', '') == option_type], key=lambda c: str(getattr(c, 'expiry', '')))
        if wc:
            exp_date = getattr(wc[0], 'expiry', None)
            exp_type = classify_expiry_type(exp_date, underlying) if exp_date else 'WEEKLY'
    try:
        from engine.position_sizer import get_lot_size
        lot_sz = get_lot_size(underlying) or 1
    except Exception:
        lot_sz = 1
    sl_prem = round(chosen_ltp * 0.82, 1) if chosen_ltp > 0 else 0.0
    t1_prem = round(chosen_ltp * 1.30, 1) if chosen_ltp > 0 else 0.0
    t2_prem = round(chosen_ltp * 1.60, 1) if chosen_ltp > 0 else 0.0
    no_chase = round(chosen_ltp * 1.06, 1) if chosen_ltp > 0 else 0.0
    now_iso = now_dt.strftime('%Y-%m-%d %H:%M:%S IST')
    contract_sym = f'{clean_sym}{int(atm_strike)}{option_type}'
    bias_dir = 'BULLISH GAP-UP' if is_bullish else 'BEARISH GAP-DOWN'
    headline = f'{strength} PREOPEN {bias_dir}: {clean_sym} {int(atm_strike)} {option_type} SETUP'
    entry_str = f'Rs{chosen_ltp:.1f}' if chosen_ltp > 0 else 'Await 09:15 open print'
    summary = f'GIFT Nifty at Rs{gift_futures_price:.1f} ({gap_pct:+.2f}% vs prev close Rs{prev_close:.1f}). Implies {bias_dir}. Entry: {entry_str} | SL: Rs{sl_prem:.1f} | T1: Rs{t1_prem:.1f} (+30%) | T2: Rs{t2_prem:.1f} (+60%). Strength: {strength} ({abs_gap:.2f}%)'
    a = AutoAlert(
        alert_id=f'aa-preopen-{clean_sym.lower()}-{option_type.lower()}-{uuid.uuid4().hex[:6]}',
        alert_type='GAMMA_BLAST', stage='EARLY_WARNING',
        symbol=clean_sym, exchange='NFO', direction=direction,
        headline=headline, summary=f'{summary} | No Chase>Rs{no_chase:.1f}',
        ltp=chosen_ltp or gift_futures_price,
        trigger_level=chosen_ltp if chosen_ltp > 0 else atm_strike,
        target_level=t1_prem if t1_prem > 0 else 0,
        stop_loss=sl_prem if sl_prem > 0 else 0,
        no_chase_boundary=no_chase, strike=atm_strike, option_type=option_type,
        contract_symbol=contract_sym, expiry_date=exp_date, expiry_type=exp_type,
        underlying_spot=gift_futures_price, option_premium=chosen_ltp if chosen_ltp > 0 else None,
        market_status='PRE_OPEN', is_live=True, environment='LIVE',
        segment='FNO_INDEX', lot_size=lot_sz, confidence=confidence,
        created_at=now_iso, ttl_seconds=3600,
        metrics={'signal_type': signal_type, 'gift_futures_price': gift_futures_price, 'prev_close': prev_close, 'gap_pct': round(gap_pct, 3), 'bias_strength': strength, 'atm_strike': atm_strike, 'option_type': option_type, 'lot_size': lot_sz, 'detector': 'PREOPEN_BIAS'},
        actionable_plan={'action': f'BUY {option_type} AT OPEN', 'contract': contract_sym, 'instrument': contract_sym, 'instrument_type': 'OPTION', 'strike': atm_strike, 'option_type': option_type, 'expiry_date': exp_date, 'expiry_type': exp_type, 'recommended_entry': entry_str, 'entry_rule': 'Buy on 1-min candle CLOSE above opening VWAP (09:16-09:20 IST).', 'no_chase': f'DO NOT CHASE above Rs{no_chase:.1f}', 'target_1': f'Rs{t1_prem:.2f}', 'target_2': f'Rs{t2_prem:.2f}', 'stop_loss': f'Rs{sl_prem:.2f}', 'risk_reward': '1:2.0 (estimated)', 'session_context': f'PRE-OPEN | GIFT {gap_pct:+.2f}% | Opens 09:15 IST'},
    )
    logger.info(f'[PreopenBias] {signal_type}: {clean_sym} GIFT={gift_futures_price:.1f} ({gap_pct:+.2f}%) -> {int(atm_strike)} {option_type}')
    return [a]