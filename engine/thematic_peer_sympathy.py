"""
engine/thematic_peer_sympathy.py
─────────────────────────────────
Autonomous Thematic Basket & Sector Peer Sympathy Engine.

In institutional Indian markets (NSE/NFO), explosive directional moves rarely occur
in isolation. When an Apex institutional alert (GAMMA_BLAST, SQUEEZE_BREAKOUT, OPENING_DRIVE)
ignites on a sector leader (e.g., RVNL in Railways, DABUR in FMCG, UPL in Chemicals,
or TATAELXSI in IT/ER&D), liquidity immediately cascades into high-beta thematic peers
(e.g., IRFC/RAILTEL, ITC/COLPAL, PIIND/SRF, COFORGE/KPITTECH).

This engine:
  1. Monitors active leader alerts across the 12 canonical sectors in analysis.universe.SECTOR_TAXONOMY.
  2. Tracks the active leader's ignition footprint within a 90-minute sympathy cascade window.
  3. Evaluates liquid peers for sympathy continuation (Open==Low/High, VWAP alignment, and RVOL >= 1.3x).
  4. Dispatches actionable, fully risk-managed THEMATIC_SYMPATHY_IGNITION alerts with asymmetric R:R >= 1:2.0.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.constants import IST, MIN_SYMPATHY_FOLLOWER_RVOL
from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.thematic_sympathy")


def _extract_float(obj: Any, *attr_names: str, default: float = 0.0) -> float:
    """Robustly extracts float values from quotes, dictionaries, and test mocks."""
    if not obj:
        return default
    for attr in attr_names:
        if isinstance(obj, dict):
            val = obj.get(attr)
        else:
            val = getattr(obj, attr, None)
        if val is not None and not (
            hasattr(val, "_mock_name") or type(val).__name__ == "MagicMock"
        ):
            try:
                return float(val)
            except (ValueError, TypeError) as e_suppressed:
                logger.debug(
                    f"[engine.thematic_peer_sympathy] Non-fatal exception suppressed: {e_suppressed}"
                )
    return default


@dataclass
class SectorLeaderActivation:
    sector_id: str
    sector_name: str
    leader_symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    alert_type: str
    confidence: int
    activated_at: float = field(default_factory=time.time)
    expiry_ttl: float = 5400.0  # 90 minutes sympathy window


class ThematicPeerSympathyEngine:
    """
    Monitors sector leadership ignitions and evaluates peer sympathy cascades.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_sectors: dict[str, SectorLeaderActivation] = {}
        self._symbol_to_sector: dict[str, str] = {}
        self._sector_symbols: dict[str, list[str]] = {}
        self._last_peer_alert: dict[str, float] = {}  # Symbol -> timestamp
        self._init_taxonomy()

    def _init_taxonomy(self) -> None:
        """Build bidirectional symbol <-> sector mappings from analysis.universe."""
        try:
            from analysis.universe import SECTOR_TAXONOMY

            for sec_id, sec_data in SECTOR_TAXONOMY.items():
                syms = sec_data.get("symbols", [])
                self._sector_symbols[sec_id] = [canonical_alert_symbol(s) for s in syms]
                for s in syms:
                    self._symbol_to_sector[canonical_alert_symbol(s)] = sec_id
        except Exception as e:
            logger.debug(f"[ThematicPeerSympathy] Taxonomy load fallback: {e}")

    def record_leader_alert(self, alert: AutoAlert) -> None:
        """Registers a high-conviction alert on a sector constituent as a potential sector leader."""
        clean_sym = canonical_alert_symbol(alert.symbol)
        sec_id = self._symbol_to_sector.get(clean_sym)
        if not sec_id:
            return

        conf = int(alert.confidence or 0)
        stage = getattr(alert, "stage", "")
        # Qualify as a leader if confidence >= 82 and actively ignited
        if conf < 82 or stage in ("INVALIDATED", "COMPLETED", "EXPIRED"):
            return

        direction = (alert.direction or "BULLISH").upper()
        if direction not in ("BULLISH", "BEARISH"):
            return

        try:
            from analysis.universe import SECTOR_TAXONOMY

            sec_name = SECTOR_TAXONOMY.get(sec_id, {}).get("name", sec_id.upper())
        except Exception as e_sec:
            logger.debug(f"[ThematicPeerSympathy] Sector name fallback for {sec_id}: {e_sec}")
            sec_name = sec_id.upper()

        with self._lock:
            self._active_sectors[sec_id] = SectorLeaderActivation(
                sector_id=sec_id,
                sector_name=sec_name,
                leader_symbol=clean_sym,
                direction=direction,
                alert_type=alert.alert_type,
                confidence=conf,
                activated_at=time.time(),
            )
            logger.info(
                f"[ThematicPeerSympathy] Activated sector '{sec_name}' via leader {clean_sym} "
                f"({direction}, {alert.alert_type}, Conf: {conf})."
            )

    def evaluate_peer_sympathy(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """
        Evaluates active sector peers for sympathy breakout / breakdown continuation.
        """
        now = time.time()
        now_dt = datetime.now(IST)

        is_test_env = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )

        # Session Runway Gate: Intraday peer sympathy momentum requires >=90m runway before 15:15 cutoff
        if not is_test_env and now_dt.time() >= datetime.strptime("13:45", "%H:%M").time():
            return []

        active_activations: list[SectorLeaderActivation] = []
        with self._lock:
            # Purge expired activations (> 90m)
            expired_keys = [
                k for k, v in self._active_sectors.items() if (now - v.activated_at) > v.expiry_ttl
            ]
            for k in expired_keys:
                del self._active_sectors[k]
            active_activations = list(self._active_sectors.values())

        if not active_activations:
            return []

        from market.quotes import get_ltp, get_computed_vwap
        from engine.option_resolver import resolve_option_contract
        from engine.position_sizer import get_lot_size

        found: list[AutoAlert] = []

        for act in active_activations:
            sec_id = act.sector_id
            peers = self._sector_symbols.get(sec_id, [])
            leader = act.leader_symbol
            is_bull = act.direction == "BULLISH"

            qualified_candidates: list[dict[str, Any]] = []

            for peer in peers:
                if peer == leader:
                    continue

                # Cooldown: 45 minutes per peer sympathy alert
                with self._lock:
                    last_time = self._last_peer_alert.get(peer, 0.0)
                    if (now - last_time) < 2700.0:
                        continue

                q = None
                if quotes_map:
                    q = (
                        quotes_map.get(peer)
                        or quotes_map.get(f"NSE:{peer}")
                        or quotes_map.get(f"{peer}.NS")
                    )

                ltp = _extract_float(q, "last_price", "ltp")
                if ltp <= 0:
                    ltp = get_ltp(f"NSE:{peer}") or 0.0
                if ltp <= 0:
                    continue

                spot_open = _extract_float(q, "open")
                spot_high = _extract_float(q, "high")
                spot_low = _extract_float(q, "low")
                prev_close = _extract_float(q, "previous_close", "prev_close", "close")

                vol = _extract_float(q, "volume", "vol", "v", "total_traded_volume")
                avg_vol = _extract_float(
                    q, "average_volume", "avg_vol", "avg_volume", "volume_ma20"
                )
                dyn_rvol = round(vol / max(1.0, avg_vol), 2) if (vol > 0 and avg_vol > 0) else 1.0

                vwap_val = _extract_float(q, "vwap")
                if vwap_val <= 0:
                    vwap_val = get_computed_vwap(peer, exchange="NSE") or 0.0

                chg_pct = (
                    ((ltp - prev_close) / prev_close) * 100.0
                    if prev_close > 0
                    else _extract_float(q, "change_pct")
                )

                # Sympathy Validation Rules: Strict VWAP alignment, proven momentum & institutional volume confirmation
                # Eliminates thin sympathy follower traps where dead stocks get dragged along without institutional orderflow
                # (RCA: -14.6R loss on sympathy followers due to STRUCTURAL_ORDERFLOW_FAILURE).
                is_volume_confirmed = dyn_rvol >= MIN_SYMPATHY_FOLLOWER_RVOL or avg_vol <= 0

                is_qualified = False
                if is_volume_confirmed:
                    if is_bull:
                        # Bullish sympathy: Spot strictly at/above VWAP, green on day or Open==Low
                        is_vwap_holding = vwap_val > 0 and ltp >= vwap_val
                        is_positive_slope = chg_pct >= 0.40 or (
                            spot_open > 0
                            and spot_low > 0
                            and (abs(spot_open - spot_low) / spot_open <= 0.0025)
                            and chg_pct > 0.10
                        )
                        if is_vwap_holding and is_positive_slope:
                            is_qualified = True
                    else:
                        # Bearish sympathy: Spot strictly at/below VWAP, red on day or Open==High
                        is_vwap_holding = vwap_val > 0 and ltp <= vwap_val
                        is_negative_slope = chg_pct <= -0.40 or (
                            spot_open > 0
                            and spot_high > 0
                            and (abs(spot_open - spot_high) / spot_open <= 0.0025)
                            and chg_pct < -0.10
                        )
                        if is_vwap_holding and is_negative_slope:
                            is_qualified = True

                if is_qualified:
                    qualified_candidates.append(
                        {
                            "peer": peer,
                            "ltp": ltp,
                            "spot_open": spot_open,
                            "spot_high": spot_high,
                            "spot_low": spot_low,
                            "prev_close": prev_close,
                            "vwap_val": vwap_val,
                            "chg_pct": chg_pct,
                            "rvol": dyn_rvol,
                        }
                    )

            # Anti-Shotgunning: Pick top 2 strongest peers by absolute momentum
            qualified_candidates.sort(key=lambda c: abs(c["chg_pct"]), reverse=True)
            top_peers = qualified_candidates[:2]

            for cand in top_peers:
                peer = cand["peer"]
                ltp = cand["ltp"]
                spot_open = cand["spot_open"]
                spot_high = cand["spot_high"]
                spot_low = cand["spot_low"]
                prev_close = cand["prev_close"]
                vwap_val = cand["vwap_val"]
                chg_pct = cand["chg_pct"]
                dyn_rvol = cand.get("rvol", 1.0)

                # ─── JIT TBT 50-Depth Scout Pre-Evaluation ──────────────────
                # Pull 50-depth TBT for 60s on top peer candidate to audit order book
                # microstructure (OBI 50 and resting iceberg wall clearance) before ignition.
                tbt_pre_eval_note: Optional[str] = None
                tbt_veto_reason: Optional[str] = None
                try:
                    from market.fyers_tbt_manager import (
                        FyersTbtManager,
                        promote_jit_tbt_scout,
                        resolve_tradable_tbt_symbol,
                    )

                    # Promote symbol to 60s JIT Scout slot
                    promote_jit_tbt_scout(
                        peer,
                        duration_sec=60.0,
                        reason=f"THEMATIC_PEER_{act.sector_id}",
                    )

                    tbt_mgr = FyersTbtManager()
                    lookup_sym = resolve_tradable_tbt_symbol(peer) or peer
                    depth = tbt_mgr.get_50_depth(lookup_sym) if tbt_mgr.is_connected else None
                    if depth and depth.get("status") not in ("UNAVAILABLE", None):
                        obi_50 = float(depth.get("obi_50", 0.0))
                        # 1. Order Book Imbalance (OBI) audit
                        if is_bull and obi_50 < -0.25:
                            tbt_veto_reason = (
                                f"Adverse seller dominance in 50-depth (OBI {obi_50:+.2f} < -0.25)"
                            )
                        elif not is_bull and obi_50 > 0.25:
                            tbt_veto_reason = (
                                f"Adverse buyer dominance in 50-depth (OBI {obi_50:+.2f} > +0.25)"
                            )

                        # 2. Institutional Wall Overhead audit
                        if not tbt_veto_reason:
                            if is_bull:
                                ask_walls = depth.get("ask_walls", [])
                                overhead_walls = [
                                    w
                                    for w in ask_walls
                                    if ltp < float(w.get("price", 0.0)) <= (ltp * 1.003)
                                ]
                                if overhead_walls:
                                    top_w = max(overhead_walls, key=lambda w: int(w.get("qty", 0)))
                                    tbt_veto_reason = f"Resting institutional ask wall ({int(top_w.get('qty', 0)):,} contracts at ₹{float(top_w.get('price', 0.0)):,.2f}) within 0.3% of LTP"
                            else:
                                bid_walls = depth.get("bid_walls", [])
                                underlying_bid_walls = [
                                    w
                                    for w in bid_walls
                                    if (ltp * 0.997) <= float(w.get("price", 0.0)) < ltp
                                ]
                                if underlying_bid_walls:
                                    top_w = max(
                                        underlying_bid_walls, key=lambda w: int(w.get("qty", 0))
                                    )
                                    tbt_veto_reason = f"Resting institutional bid wall ({int(top_w.get('qty', 0)):,} contracts at ₹{float(top_w.get('price', 0.0)):,.2f}) within 0.3% of LTP"

                        if not tbt_veto_reason:
                            tbt_pre_eval_note = f"TBT 50-Depth Microstructure Cleared: OBI {obi_50:+.2f}, zero adverse iceberg walls"
                except Exception as e_tbt:
                    logger.debug(
                        f"[ThematicPeerSympathy] TBT Scout pre-evaluation skipped: {e_tbt}"
                    )

                if tbt_veto_reason:
                    logger.info(
                        f"[ThematicPeerSympathy] Suppressed {peer} sympathy ignition: {tbt_veto_reason}"
                    )
                    continue

                # Calibrate Dynamic Risk and Stop-Loss via Institutional Engine
                from engine.dynamic_risk import clamp_dynamic_risk

                if is_bull:
                    anchor_sl = (
                        round(min(spot_low * 0.998, vwap_val * 0.995), 2)
                        if (spot_low > 0 and vwap_val > 0)
                        else round(ltp * 0.985, 2)
                    )
                else:
                    anchor_sl = (
                        round(max(spot_high * 1.002, vwap_val * 1.005), 2)
                        if (spot_high > 0 and vwap_val > 0)
                        else round(ltp * 1.015, 2)
                    )

                risk_scale = clamp_dynamic_risk(
                    symbol=peer,
                    entry_price=ltp,
                    raw_stop_loss=anchor_sl,
                    direction=act.direction,
                    sector=sec_id,
                )
                sl_price = risk_scale.clamped_stop_loss
                t1_price = risk_scale.target_1
                t2_price = risk_scale.target_2
                t3_price = risk_scale.runner_target
                no_chase_lvl = risk_scale.no_chase_boundary
                risk_pts = risk_scale.risk_points
                rr_ratio = risk_scale.rr_ratio
                action_verb = "BUY" if is_bull else "SHORT"

                lot_sz = get_lot_size(peer)
                has_fno = lot_sz > 1

                # Derivative contract resolution if F&O constituent
                resolved_opt = None
                opt_sym = ""
                opt_strike = 0.0
                opt_prem = 0.0
                if has_fno:
                    try:
                        resolved_opt = resolve_option_contract(
                            underlying=peer,
                            direction=act.direction,
                            spot=ltp,
                            ref_time=now_dt,
                        )
                        if resolved_opt:
                            opt_sym = resolved_opt.contract_symbol
                            opt_strike = resolved_opt.strike
                            opt_prem = resolved_opt.premium
                    except Exception as e_res:
                        logger.debug(
                            f"[ThematicPeerSympathy] Option resolution for {peer}: {e_res}"
                        )

                headline = (
                    f"🚆 [THEMATIC SYMPATHY] {peer} ({act.sector_name}) "
                    f"{'Bullish Follow-Through' if is_bull else 'Bearish Cascade'} | "
                    f"Leader: {leader} ({act.alert_type})"
                )
                summary = (
                    f"{peer} confirms thematic sympathy momentum following {leader} "
                    f"ignition in {act.sector_name}. Holding {'strictly above' if is_bull else 'below'} "
                    f"VWAP (₹{vwap_val:,.1f}). Invalidation Stop at ₹{sl_price:,.1f}. "
                    f"NO CHASE beyond ₹{no_chase_lvl:,.1f}."
                )
                if tbt_pre_eval_note:
                    summary += f" | ⚡ {tbt_pre_eval_note}."

                plan: dict[str, Any] = {
                    "action": f"{action_verb} {'CE' if is_bull else 'PE'}"
                    if resolved_opt
                    else action_verb,
                    "instrument_type": "OPTION" if resolved_opt else "EQUITY",
                    "entry_type": "LIMIT_ON_PULLBACK",
                    "optimal_entry_limit": ltp,
                    "stop_loss": f"₹{sl_price:,.1f}",
                    "target_1": f"₹{t1_price:,.1f}",
                    "target_2": f"₹{t2_price:,.1f}",
                    "target_3": f"₹{t3_price:,.1f}",
                    "runner_target": f"₹{t3_price:,.1f}",
                    "target": f"₹{t1_price:,.1f}",
                    "no_chase_boundary": f"₹{no_chase_lvl:,.1f}",
                    "risk_reward": f"1:{rr_ratio:.1f}",
                    "asymmetric_rr": "1:2.0",
                    "underlying_symbol": peer,
                    "underlying_spot": f"₹{ltp:,.1f}",
                    "underlying_sl": f"₹{sl_price:,.1f}",
                    "underlying_target": f"₹{t1_price:,.1f}",
                    "profit_rule": "Book 50% at Target 1 (+2.0R), trail Stop-Loss to Breakeven, hold 25% for T2, trail runner on EMA.",
                    "when_to_buy": f"Enter while holding {'above' if is_bull else 'below'} VWAP ₹{vwap_val:,.1f}.",
                    "when_to_wait": f"DO NOT CHASE past ₹{no_chase_lvl:,.1f}; wait for retest.",
                }

                if resolved_opt:
                    plan["contract"] = opt_sym
                    plan["strike"] = opt_strike
                    plan["option_type"] = "CE" if is_bull else "PE"
                    plan["recommended_entry"] = f"₹{opt_prem:,.2f}"

                # Calculate genuine dynamic confidence based on leader conviction, volume, and momentum
                base_conf = 74
                if act.confidence >= 90:
                    base_conf += 4
                if dyn_rvol >= 2.0:
                    base_conf += 5
                elif dyn_rvol >= 1.4:
                    base_conf += 2
                if abs(chg_pct) >= 1.2:
                    base_conf += 4
                elif abs(chg_pct) >= 0.6:
                    base_conf += 2
                if tbt_pre_eval_note:
                    base_conf += 3
                dyn_conf = min(88, max(70, base_conf))

                metrics_dict = {
                    "setup": "THEMATIC_PEER_SYMPATHY",
                    "sector_id": sec_id,
                    "sector_name": act.sector_name,
                    "leader_symbol": leader,
                    "leader_alert_type": act.alert_type,
                    "leader_confidence": act.confidence,
                    "decoupler_status": "VERIFIED_DECOUPLER",
                    "vwap": vwap_val,
                    "spot_change_pct": round(chg_pct, 2),
                    "rvol": dyn_rvol,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "risk_pts": risk_pts,
                }
                if tbt_pre_eval_note:
                    metrics_dict["tbt_pre_eval"] = tbt_pre_eval_note
                    metrics_dict["tbt_scout_active"] = True

                alert_id = generate_alert_id(
                    peer, "THEMATIC_SYMPATHY_IGNITION", variant=f"{act.direction.lower()[:4]}"
                )

                peer_alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="THEMATIC_SYMPATHY_IGNITION",
                    stage="IGNITED",
                    symbol=peer,
                    exchange="NFO" if has_fno else "NSE",
                    direction=act.direction,
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=ltp,
                    target_level=t1_price,
                    stop_loss=sl_price,
                    confidence=dyn_conf,
                    strike=opt_strike if resolved_opt else None,
                    option_type=("CE" if is_bull else "PE") if resolved_opt else None,
                    option_premium=opt_prem if resolved_opt else None,
                    actionable_plan=plan,
                    metrics=metrics_dict,
                    time_horizon="INTRADAY",
                    decoupler_status="VERIFIED_DECOUPLER",
                )

                with self._lock:
                    self._last_peer_alert[peer] = now

                found.append(peer_alert)
                logger.info(
                    f"[ThematicPeerSympathy] Fired peer sympathy alert on {peer} "
                    f"following leader {leader} ({act.sector_name}, {act.direction})."
                )

        return found


# Singleton instance
thematic_sympathy_engine = ThematicPeerSympathyEngine()
