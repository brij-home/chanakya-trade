"""
web/routers/intelligence_api.py
───────────────────────────────
Modular AI Council, Persona Track-Record, Whale Flow, Model Governance,
Trade Journal, Security 360, Strategy/Chain Integrity, Pattern Learning,
and Terminal Setup routes extracted from web/skills.py via Strangler pattern.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from web.routers.common import (
    normalize_symbol_and_exchange as _normalize_symbol_and_exchange,
    skill_err as _err,
    skill_ok as _ok,
)

logger = logging.getLogger("chanakya.web.routers.intelligence")
router = APIRouter(tags=["OpenClaw Skills"])


class CouncilRequest(BaseModel):
    symbol: str
    council: str = "breakout"
    exchange: str = "NSE"


class PersonaAnalyzeRequest(BaseModel):
    symbol: str
    persona_id: str
    exchange: str = "NSE"


def _persona_council_sync(req: CouncilRequest):
    sym = (req.symbol or "RELIANCE").upper().strip()
    council = (req.council or "breakout").lower().strip()
    exch = (req.exchange or "NSE").upper().strip()
    cache_key = f"persona_council_{council}_{sym}_{exch}"
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_macro(cache_key)
        if cached and isinstance(cached, dict) and cached.get("symbol") == sym:
            return _ok(cached)
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    from agent.persona_agent import run_council

    res = run_council(
        council_name=council,
        symbol=sym,
        exchange=exch,
        llm_provider="auto",
    )
    if "signals" in res:
        res["signals"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in res["signals"]]

    try:
        from engine.analysis_cache import analysis_cache

        analysis_cache.save_macro(cache_key, res, ttl_minutes=15)
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")
    return _ok(res)


@router.post("/persona/council")
@router.post("/skills/persona/council")
async def skill_persona_council(req: CouncilRequest):
    """Run a specialized council of research-framework lenses on a stock symbol."""
    try:
        return await asyncio.to_thread(_persona_council_sync, req)
    except Exception as e:
        raise _err(str(e))


def _persona_analyze_sync(req: PersonaAnalyzeRequest):
    sym = (req.symbol or "RELIANCE").upper().strip()
    persona_id = (req.persona_id or "minervini").lower().strip()
    exch = (req.exchange or "NSE").upper().strip()
    cache_key = f"persona_analyze_{persona_id}_{sym}_{exch}"
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_macro(cache_key)
        if cached and isinstance(cached, dict) and cached.get("persona") == persona_id:
            return _ok(cached)
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")

    from agent.persona_agent import run_persona_analysis

    sig = run_persona_analysis(
        persona_id=persona_id,
        symbol=sym,
        exchange=exch,
        llm_provider="auto",
    )
    res = sig.to_dict() if hasattr(sig, "to_dict") else sig
    try:
        from engine.analysis_cache import analysis_cache

        analysis_cache.save_macro(cache_key, res, ttl_minutes=15)
    except Exception as e_suppressed:
        logger.debug(f"[web.skills] Non-fatal exception suppressed: {e_suppressed}")
    return _ok(res)


@router.post("/persona/analyze")
@router.post("/skills/persona/analyze")
async def skill_persona_analyze(req: PersonaAnalyzeRequest):
    """Analyze a stock through a selected research-framework lens."""
    try:
        return await asyncio.to_thread(_persona_analyze_sync, req)
    except Exception as e:
        raise _err(str(e))


class PersonaTrackRecordRequest(BaseModel):
    sector: Optional[str] = None
    regime: Optional[str] = None


@router.get("/persona/track_records")
@router.post("/persona/track_records")
@router.get("/skills/persona/track_records")
@router.post("/skills/persona/track_records")
async def skill_persona_track_records(req: Optional[PersonaTrackRecordRequest] = None):
    """Retrieve self-evolving empirical track records and dynamic weighting multipliers for all 13 personas."""
    try:
        from agent.persona_tracker import get_persona_tracker

        tracker = get_persona_tracker()
        sector = req.sector if req else None
        regime = req.regime if req else None
        records = tracker.get_all_track_records(sector=sector, regime=regime)
        return _ok({"track_records": records, "total_personas": len(records)})
    except Exception as e:
        raise _err(str(e))


class PostMortemRequest(BaseModel):
    persona_id: str
    symbol: str
    outcome_status: str
    realized_r: float
    entry_price: float
    exit_price: float
    sector: Optional[str] = "Broad Market"


@router.post("/persona/post_mortem")
@router.post("/skills/persona/post_mortem")
async def skill_persona_post_mortem(req: PostMortemRequest):
    """Generate an institutional trade retrospective analysis and update persona heuristic memory."""
    try:
        from agent.persona_tracker import get_persona_tracker

        tracker = get_persona_tracker()
        res = tracker.generate_post_mortem(
            persona_id=req.persona_id,
            symbol=req.symbol,
            outcome_status=req.outcome_status,
            realized_r=req.realized_r,
            entry_price=req.entry_price,
            exit_price=req.exit_price,
            sector=req.sector or "Broad Market",
        )
        return _ok(res)
    except Exception as e:
        raise _err(str(e))


class WhaleFlowsRequest(BaseModel):
    investor: Optional[str] = None
    sector: Optional[str] = None
    min_deal_cr: Optional[float] = 0.0


@router.get("/whale_flows")
@router.post("/whale_flows")
@router.get("/skills/whale_flows")
@router.post("/skills/whale_flows")
async def skill_whale_flows(req: Optional[WhaleFlowsRequest] = None):
    """Retrieve Indian marquee superstar investor bulk/block deals and SAST accumulations."""
    try:
        from analysis.whale_tracker import get_whale_flows

        inv = req.investor if req else None
        sec = req.sector if req else None
        min_cr = req.min_deal_cr if (req and req.min_deal_cr is not None) else 0.0
        res = get_whale_flows(investor_filter=inv, sector_filter=sec, min_deal_cr=min_cr)
        return _ok(res)
    except Exception as e:
        raise _err(str(e))


class InstrumentResolveRequest(BaseModel):
    query: str = "NIFTY"


class MarketSessionRequest(BaseModel):
    exchange: Optional[str] = "NSE"


@router.get("/instruments/resolve")
@router.post("/instruments/resolve")
async def skill_instruments_resolve(
    req: Optional[InstrumentResolveRequest] = None, query: Optional[str] = None
):
    """Resolve and normalize any symbol or user query into a CanonicalInstrument master record."""
    try:
        from market.instruments import resolve_canonical_instrument

        q = (req.query if req and req.query else query) or "NIFTY"
        instr = resolve_canonical_instrument(q)
        return _ok(instr.to_dict())
    except Exception as e:
        raise _err(str(e))


@router.get("/market_session")
@router.post("/market_session")
async def skill_market_session(
    req: Optional[MarketSessionRequest] = None, exchange: Optional[str] = "NSE"
):
    """Evaluate live exchange operational session state (PRE_OPEN, OPEN, POST_CLOSE, CLOSED)."""
    try:
        from market.instruments import get_market_session_state

        exch = (req.exchange if req and req.exchange else exchange) or "NSE"
        state = get_market_session_state(exchange=exch)  # type: ignore
        return _ok(state.to_dict())
    except Exception as e:
        raise _err(str(e))


class ModelManifestRequest(BaseModel):
    model_id: str = "macro.transmission.v1"


@router.get("/models/list")
@router.post("/models/list")
async def skill_models_list():
    """Retrieve all registered quantitative and macro model specifications and versions."""
    try:
        from engine.model_governance import list_all_models

        models = list_all_models()
        return _ok({"models": models, "total_models": len(models)})
    except Exception as e:
        raise _err(str(e))


@router.get("/models/manifest")
@router.post("/models/manifest")
async def skill_models_manifest(
    req: Optional[ModelManifestRequest] = None, model_id: Optional[str] = None
):
    """Retrieve detailed model manifest including assumptions, applicability limits, and methodology."""
    try:
        from engine.model_governance import get_model_manifest

        m_id = (req.model_id if req and req.model_id else model_id) or "macro.transmission.v1"
        manifest = get_model_manifest(m_id)
        if not manifest:
            raise HTTPException(status_code=404, detail=f"Model manifest not found: {m_id}")
        return _ok(manifest.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        raise _err(str(e))


class JournalAddRequest(BaseModel):
    symbol: str
    direction: str = "BUY"
    entry_price: float
    qty: int
    stop_loss: float
    target: float
    setup_type: Optional[str] = "SYSTEMATIC_BREAKOUT"
    thesis: Optional[str] = ""
    order_id: Optional[str] = None


@router.post("/journal/list", operation_id="skill_journal_list_post")
@router.get("/journal/list", operation_id="skill_journal_list_get")
async def skill_journal_list(status: Optional[str] = None):
    """Retrieve all trade journal records and analytical payoff status."""
    try:
        from engine.journal import get_trade_journal

        mgr = get_trade_journal()
        entries = mgr.list_entries(status=status)
        return _ok({"entries": entries, "total_entries": len(entries)})
    except Exception as e:
        raise _err(str(e))


@router.post("/journal/add")
async def skill_journal_add(req: JournalAddRequest):
    """Record a trade entry in the authoritative trade journal."""
    try:
        from engine.journal import get_trade_journal

        mgr = get_trade_journal()
        entry = mgr.add_entry(
            symbol=req.symbol,
            direction=req.direction.upper(),  # type: ignore
            entry_price=req.entry_price,
            qty=req.qty,
            stop_loss=req.stop_loss,
            target=req.target,
            setup_type=req.setup_type or "SYSTEMATIC_BREAKOUT",
            thesis=req.thesis or "",
            order_id=req.order_id,
        )
        return _ok(entry.to_dict())
    except Exception as e:
        raise _err(str(e))


@router.post("/journal/stats", operation_id="skill_journal_stats_post")
@router.get("/journal/stats", operation_id="skill_journal_stats_get")
async def skill_journal_stats():
    """Compute institutional performance analytics (Win Rate, Profit Factor, Expectancy R)."""
    try:
        from engine.journal import get_trade_journal

        mgr = get_trade_journal()
        stats = mgr.compute_statistics()
        return _ok(stats.to_dict())
    except Exception as e:
        raise _err(str(e))


class Security360Request(BaseModel):
    """Security-360 input. Prices always come from a server-side quote provider."""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(default="RELIANCE", min_length=1, max_length=32)


@router.post("/security_360", operation_id="skill_security_360_post")
@router.get("/security_360", operation_id="skill_security_360_get")
async def skill_security_360(
    req: Optional[Security360Request] = None, symbol: Optional[str] = None
):
    """Compile comprehensive 360-degree security intelligence dossier with methodology lenses."""
    try:
        from engine.security_360 import build_security_360_dossier

        sym = (req.symbol if req and req.symbol else symbol) or "RELIANCE"
        # A browser must not be able to influence trade-facing valuation or
        # levels with a stale or manipulated price.
        dossier = build_security_360_dossier(symbol=sym)
        return _ok(dossier.to_dict())
    except Exception as e:
        raise _err(str(e))


class StrategyManifestRequest(BaseModel):
    strategy_id: str = "strategy_v1"
    strategy_name: str = "Custom Strategy"
    strategy_version: str = "1.0.0"
    universe: list[str] = ["RELIANCE", "TCS"]
    data_snapshot_start: str = "2022-01-01"
    data_snapshot_end: str = "2024-01-01"
    benchmark: str = "NIFTY50"
    parameters: dict = {}
    notes: str = ""


@router.post("/strategy_manifest")
async def skill_strategy_manifest(req: StrategyManifestRequest):
    """Create an immutable, cryptographically-sealed Strategy Run Manifest."""
    try:
        from engine.strategy_manifest import create_run_manifest

        manifest = create_run_manifest(
            strategy_id=req.strategy_id,
            strategy_name=req.strategy_name,
            strategy_version=req.strategy_version,
            universe=req.universe,
            data_snapshot_start=req.data_snapshot_start,
            data_snapshot_end=req.data_snapshot_end,
            benchmark=req.benchmark,
            parameters=req.parameters,
            notes=req.notes,
        )
        return _ok(manifest.to_dict())
    except Exception as e:
        raise _err(str(e))


class ChainIntegrityRequest(BaseModel):
    symbol: str = "NIFTY"
    expiry: str = "2027-09-25"
    underlying_price: float = 22000.0
    chain_rows: list[dict] = []
    chain_timestamp_utc: Optional[str] = None


@router.post("/options_chain_integrity")
async def skill_options_chain_integrity(req: ChainIntegrityRequest):
    """Validate an options chain snapshot against institutional data quality standards."""
    try:
        from engine.options_chain_integrity import validate_options_chain

        report = validate_options_chain(
            symbol=req.symbol,
            expiry=req.expiry,
            underlying_price=req.underlying_price,
            chain_rows=req.chain_rows,
            chain_timestamp_utc=req.chain_timestamp_utc,
        )
        return _ok(report.to_dict())
    except Exception as e:
        raise _err(str(e))


class PatternMatchSkillRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"


class RegisterExplosiveMoveRequest(BaseModel):
    symbol: str
    move_pct: float
    rvol_surge: float = 2.0
    catalyst: str = ""
    date_str: Optional[str] = None


@router.get("/learned_patterns")
async def skill_get_learned_patterns():
    """Retrieve all learned explosive move archetypes and deciding factor footprints."""
    try:
        from engine.learning_engine import pattern_learning_engine

        archetypes = pattern_learning_engine.get_learned_archetypes()
        return _ok(
            {
                "count": len(archetypes),
                "archetypes": archetypes,
            }
        )
    except Exception as e:
        raise _err(str(e))


@router.post("/evaluate_pattern_match")
async def skill_evaluate_pattern_match(req: PatternMatchSkillRequest):
    """Evaluate candidate stock against learned pre-blast archetypes to detect explosive setups early."""
    try:
        from engine.learning_engine import pattern_learning_engine

        res = pattern_learning_engine.evaluate_candidate(symbol=req.symbol)
        return _ok(
            {
                "symbol": res.symbol,
                "similarity_score": res.similarity_score,
                "closest_archetype": res.closest_archetype,
                "matched_factors": res.matched_factors,
                "is_explosive_candidate": res.is_explosive_candidate,
                "recommended_entry_action": res.recommended_entry_action,
                "expected_asymmetry_rr": res.expected_asymmetry_rr,
            }
        )
    except Exception as e:
        raise _err(str(e))


@router.post("/register_explosive_move")
async def skill_register_explosive_move(req: RegisterExplosiveMoveRequest):
    """Register and learn from a newly confirmed explosive move, persisting its pre-blast factors."""
    try:
        from engine.learning_engine import pattern_learning_engine

        fp = pattern_learning_engine.register_explosive_move(
            symbol=req.symbol,
            move_pct=req.move_pct,
            rvol_surge=req.rvol_surge,
            catalyst=req.catalyst,
            date_str=req.date_str,
        )
        return _ok(fp.to_dict())
    except Exception as e:
        raise _err(str(e))


@router.get("/terminal/target_setup")
@router.post("/terminal/target_setup")
async def skill_terminal_target_setup(symbol: str = "NIFTY", timeframe: str = "15m"):
    """Lightweight grounded setup context for ChartStudioView sidecar (no synthetic numbers)."""
    try:
        from analysis.market_structure import analyze_market_structure
        from analysis.volume_profile import analyze_volume_profile
        from market.history import get_ohlcv
        from market.quotes import get_quote

        clean_sym, exch = _normalize_symbol_and_exchange(symbol, "NSE")
        quotes = await asyncio.to_thread(get_quote, [f"{exch}:{clean_sym}"])
        q_val = next(iter(quotes.values()), None) if isinstance(quotes, dict) else None
        if isinstance(q_val, dict):
            ltp = float(q_val.get("ltp") or q_val.get("last_price") or 0.0)
            chg_pct = float(q_val.get("change_pct") or 0.0)
        elif q_val is not None:
            ltp = float(getattr(q_val, "ltp", 0.0) or 0.0)
            chg_pct = float(getattr(q_val, "change_pct", 0.0) or 0.0)
        else:
            ltp, chg_pct = 0.0, 0.0

        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1D": "day", "1W": "week"}
        hist_tf = tf_map.get(timeframe, "day")
        df = await asyncio.to_thread(get_ohlcv, clean_sym, exchange=exch, interval=hist_tf, days=20)
        atr_val = None
        if df is not None and not df.empty and len(df) >= 14:
            highs = df["high"].astype(float)
            lows = df["low"].astype(float)
            closes = df["close"].astype(float)
            prev_c = closes.shift(1).fillna(closes)
            tr = (
                (highs - lows)
                .combine((highs - prev_c).abs(), max)
                .combine((lows - prev_c).abs(), max)
            )
            raw_atr = float(tr.tail(14).mean())
            if raw_atr > 0:
                atr_val = round(raw_atr, 2)

        vp_data = {}
        try:
            vp = await asyncio.to_thread(
                analyze_volume_profile, clean_sym, df=df, exchange=exch, timeframe=hist_tf
            )
            if vp:
                vp_data = {
                    "poc": round(float(vp.poc_price), 2) if getattr(vp, "poc_price", 0) else None,
                    "vah": round(float(vp.vah_price), 2) if getattr(vp, "vah_price", 0) else None,
                    "val": round(float(vp.val_price), 2) if getattr(vp, "val_price", 0) else None,
                }
        except Exception as e_vp:
            logger.debug(f"[web.skills] Volume profile fallback skipped for {clean_sym}: {e_vp}")

        ob_data = None
        try:
            smc = await asyncio.to_thread(
                analyze_market_structure, clean_sym, df=df, exchange=exch, timeframe=hist_tf
            )
            obs = getattr(smc, "order_blocks", None) or []
            if obs:
                ob = obs[-1]
                top = getattr(ob, "top", None) or (ob.get("top") if isinstance(ob, dict) else None)
                bot = getattr(ob, "bottom", None) or (
                    ob.get("bottom") if isinstance(ob, dict) else None
                )
                if top and bot:
                    ob_data = {"top": round(float(top), 2), "bottom": round(float(bot), 2)}
        except Exception as e_smc:
            logger.debug(f"[web.skills] Order block fallback skipped for {clean_sym}: {e_smc}")

        stop_loss = round(ltp - 1.5 * atr_val, 2) if (ltp > 0 and atr_val) else None
        target_1 = round(ltp + 3.0 * atr_val, 2) if (ltp > 0 and atr_val) else None
        return _ok(
            {
                "symbol": clean_sym,
                "exchange": exch,
                "timeframe": timeframe,
                "live_quote": {"ltp": ltp if ltp > 0 else None, "change_pct": round(chg_pct, 2)},
                "volume_profile": vp_data,
                "order_block": ob_data,
                "atr": atr_val,
                "stop_loss": stop_loss,
                "target_1": target_1,
            }
        )
    except Exception as e:
        raise _err(str(e))
