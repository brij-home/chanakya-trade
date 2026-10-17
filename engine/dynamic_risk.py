"""
engine/dynamic_risk.py
──────────────────────
Hierarchical Dynamic Risk Scaling & Volatility Normalization Engine for Indian Markets (NSE, BSE, NFO, MCX).

Institutional Invariants:
1. Multi-Tier Hybrid Model: Risk is never evaluated on a single variable (pure price or pure percentage).
   It scales across 5 granular hierarchies:
     - Tier 1: Instrument Segment (Cash Equity vs Index Options vs Stock F&O vs MCX Commodities)
     - Tier 2: Nominal Price Band (Sub-₹100 Micro, ₹100-₹500, ₹500-₹2,500, ₹2,500-₹10,000, >₹10,000)
     - Tier 3: Sector & Asset Beta Volatility Profile (High-Beta Momentum, Cyclical, Defensive, Core)
     - Tier 4: Macro Volatility Regime (India VIX Compression, Normal, Elevated, Tail Risk)
     - Tier 5: Exchange & Regulatory Guardrails (SEBI Circuit Headroom, Physical Delivery Margin)
2. Structural Invalidation Sanctity: The technical stop-loss level is anchored to deterministic market structure
   (OB, Swing Low/High, 15m ORB, VWAP band), but mathematically bounded by ATR volatility and price tier floors.
3. Asymmetric Expectancy: Every validated setup produces an Actionable Blueprint:
   Stop-Loss, Target 1 (+2R, scale 50% & SL to breakeven), Target 2 (+4R extension), Runner (+6R+),
   and strict No-Chase boundary with R:R >= 1:2.0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from market.instruments import STANDARD_LOT_SIZES
from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.dynamic_risk")


# =============================================================================
# 1. TIER 2: NOMINAL PRICE BAND & ABSOLUTE RISK FLOORS
# =============================================================================


@dataclass(frozen=True)
class PriceTierRule:
    tier_name: str
    min_price: float
    max_price: float
    abs_min_risk_pts: float
    min_opt_premium: float
    tick_size: float
    description: str


PRICE_TIER_RULES: list[PriceTierRule] = [
    PriceTierRule(
        tier_name="SUB_100_MICRO",
        min_price=0.0,
        max_price=100.0,
        abs_min_risk_pts=0.10,
        min_opt_premium=0.50,
        tick_size=0.01,
        description="Sub-₹100 low-ticket equities & F&O underlyings (SUZLON, IRFC, IDEA, YESBANK). Prevents inverted R:R.",
    ),
    PriceTierRule(
        tier_name="SMALL_MID_100_250",
        min_price=100.0,
        max_price=250.0,
        abs_min_risk_pts=0.25,
        min_opt_premium=1.00,
        tick_size=0.01,
        description="Sub-₹250 liquid equities under SEBI 1-paisa tick size mandate (TATASTEEL, BEL, BHEL, IOC).",
    ),
    PriceTierRule(
        tier_name="SMALL_MID_100_500",
        min_price=250.0,
        max_price=500.0,
        abs_min_risk_pts=0.50,
        min_opt_premium=1.50,
        tick_size=0.05,
        description="Small-to-mid liquid equities ₹250-₹500 (ITC, DELHIVERY, RVNL, TATAPOWER).",
    ),
    PriceTierRule(
        tier_name="MID_LARGE_500_2500",
        min_price=500.0,
        max_price=2500.0,
        abs_min_risk_pts=2.00,
        min_opt_premium=3.00,
        tick_size=0.05,
        description="Core institutional heavyweights (INFY, ICICIBANK, RELIANCE, SBIN, LT).",
    ),
    PriceTierRule(
        tier_name="HIGH_TICKET_2500_10000",
        min_price=2500.0,
        max_price=10000.0,
        abs_min_risk_pts=6.00,
        min_opt_premium=8.00,
        tick_size=0.05,
        description="High-ticket institutional equities (TCS, BAJFINANCE, DIXON, ULTRACEMCO).",
    ),
    PriceTierRule(
        tier_name="ULTRA_HIGH_ABOVE_10000",
        min_price=10000.0,
        max_price=float("inf"),
        abs_min_risk_pts=25.00,
        min_opt_premium=20.00,
        tick_size=0.05,
        description="Ultra-high ticket equities (MRF, PAGEIND, BOSCHLTD, SHREECEM).",
    ),
]


def resolve_price_tier(price: float) -> PriceTierRule:
    """Resolves the nominal price tier rule for a given spot/entry price."""
    p = max(0.01, float(price))
    for rule in PRICE_TIER_RULES:
        if rule.min_price <= p < rule.max_price:
            return rule
    return PRICE_TIER_RULES[-1]


# =============================================================================
# 2. TIER 3: SECTOR & BETA VOLATILITY PROFILES
# =============================================================================


@dataclass(frozen=True)
class SectorRiskProfile:
    category: str
    beta_range: tuple[float, float]
    default_beta: float
    trailing_atr_multiplier: float
    max_sector_capital_pct: float
    max_sector_risk_pct: float
    description: str


SECTOR_RISK_PROFILES: dict[str, SectorRiskProfile] = {
    "HIGH_BETA_MOMENTUM": SectorRiskProfile(
        category="HIGH_BETA_MOMENTUM",
        beta_range=(1.6, 2.8),
        default_beta=2.0,
        trailing_atr_multiplier=2.0,
        max_sector_capital_pct=25.0,
        max_sector_risk_pct=4.0,
        description="High-velocity momentum (Railways, Defence, PSU Banks, Power, Capital Goods, Realty).",
    ),
    "CYCLICAL_COMMODITY": SectorRiskProfile(
        category="CYCLICAL_COMMODITY",
        beta_range=(1.2, 1.6),
        default_beta=1.4,
        trailing_atr_multiplier=1.5,
        max_sector_capital_pct=20.0,
        max_sector_risk_pct=3.0,
        description="Macro-cyclical & commodity sensitive (Metals, Energy, Oil & Gas, Chemicals).",
    ),
    "DEFENSIVE_QUALITY": SectorRiskProfile(
        category="DEFENSIVE_QUALITY",
        beta_range=(0.5, 0.85),
        default_beta=0.7,
        trailing_atr_multiplier=1.1,
        max_sector_capital_pct=35.0,
        max_sector_risk_pct=5.0,
        description="Low-beta defensives (FMCG, Pharma, Healthcare, Consumer Staples).",
    ),
    "CORE_BENCHMARK": SectorRiskProfile(
        category="CORE_BENCHMARK",
        beta_range=(0.85, 1.2),
        default_beta=1.0,
        trailing_atr_multiplier=1.3,
        max_sector_capital_pct=30.0,
        max_sector_risk_pct=4.5,
        description="Benchmark anchors (Private Banks, Tier-1 IT, Auto, Telecom).",
    ),
}

_SECTOR_TAXONOMY_MAP: dict[str, str] = {
    "railways": "HIGH_BETA_MOMENTUM",
    "rail": "HIGH_BETA_MOMENTUM",
    "defence": "HIGH_BETA_MOMENTUM",
    "defense": "HIGH_BETA_MOMENTUM",
    "power": "HIGH_BETA_MOMENTUM",
    "infra": "HIGH_BETA_MOMENTUM",
    "realty": "HIGH_BETA_MOMENTUM",
    "capital_goods": "HIGH_BETA_MOMENTUM",
    "psu": "HIGH_BETA_MOMENTUM",
    "psu_banks": "HIGH_BETA_MOMENTUM",
    "metals": "CYCLICAL_COMMODITY",
    "metal": "CYCLICAL_COMMODITY",
    "energy": "CYCLICAL_COMMODITY",
    "oil": "CYCLICAL_COMMODITY",
    "chemicals": "CYCLICAL_COMMODITY",
    "fmcg": "DEFENSIVE_QUALITY",
    "pharma": "DEFENSIVE_QUALITY",
    "healthcare": "DEFENSIVE_QUALITY",
    "consumer": "DEFENSIVE_QUALITY",
    "banking": "CORE_BENCHMARK",
    "bank": "CORE_BENCHMARK",
    "it": "CORE_BENCHMARK",
    "auto": "CORE_BENCHMARK",
    "telecom": "CORE_BENCHMARK",
}


def resolve_sector_risk_profile(symbol_or_sector: str) -> SectorRiskProfile:
    """Resolves the sector beta risk profile from sector ID or symbol lookup."""
    clean = str(symbol_or_sector).lower().strip()
    # 1. Direct sector ID match
    if clean in _SECTOR_TAXONOMY_MAP:
        cat_key = _SECTOR_TAXONOMY_MAP[clean]
        return SECTOR_RISK_PROFILES[cat_key]

    # 2. Symbol taxonomy reverse lookup from analysis.universe
    try:
        from analysis.universe import SECTOR_TAXONOMY

        canon_sym = canonical_alert_symbol(symbol_or_sector)
        for sec_id, sec_data in SECTOR_TAXONOMY.items():
            syms = [canonical_alert_symbol(s) for s in sec_data.get("symbols", [])]
            if canon_sym in syms:
                cat_key = _SECTOR_TAXONOMY_MAP.get(sec_id.lower(), "CORE_BENCHMARK")
                return SECTOR_RISK_PROFILES[cat_key]
    except Exception as e:
        logger.debug(f"[DynamicRisk] Sector taxonomy lookup fallback for {symbol_or_sector}: {e}")

    return SECTOR_RISK_PROFILES["CORE_BENCHMARK"]


# =============================================================================
# 3. TIER 4: MACRO VIX REGIME SIZING MULTIPLIER
# =============================================================================


def get_vix_regime_multiplier(vix: Optional[float] = None) -> tuple[float, str]:
    """
    Returns the dynamic volatility budget multiplier and regime note based on India VIX.
    - Compression (VIX < 12.0) -> 0.75x (reduces size during chop/low follow-through)
    - Normal (12.0 <= VIX <= 18.0) -> 1.00x (full institutional edge)
    - Elevated (18.0 < VIX <= 25.0) -> 0.70x (defensive risk contraction)
    - Tail Risk (VIX > 25.0) -> 0.50x (extreme IV crush hazard, mandate defined risk)
    """
    if vix is None or vix <= 0:
        try:
            from engine.market_regime_gate import get_cached_regime

            reg = get_cached_regime()
            if reg and reg.vix:
                vix = float(reg.vix)
        except Exception as e_suppressed:
            logger.debug(f"[engine.dynamic_risk] Non-fatal exception suppressed: {e_suppressed}")

    if vix is None or vix <= 0:
        return 1.0, "NORMAL_MARKET"

    if vix < 12.0:
        return (
            0.75,
            f"VIX_COMPRESSION ({vix:.1f} < 12.0: Risk scaled to 75% due to low momentum follow-through)",
        )
    if vix <= 18.0:
        return 1.00, f"VIX_OPTIMAL ({vix:.1f}: Normal 100% institutional risk budget)"
    if vix <= 25.0:
        return (
            0.70,
            f"VIX_ELEVATED ({vix:.1f} > 18.0: Risk scaled down to 70% for volatility defense)",
        )
    return (
        0.50,
        f"VIX_TAIL_RISK ({vix:.1f} > 25.0: Risk halved to 50%; mandate defined-risk structures)",
    )


# =============================================================================
# 4. TIER 1 & 5: SEGMENT & INSTRUMENT CLASSIFICATION
# =============================================================================


def resolve_segment_profile(symbol: str) -> tuple[str, int, bool]:
    """
    Resolves the market segment, lot size, and F&O status for a symbol.
    Returns: (segment_name, lot_size, is_fno)
    """
    clean = canonical_alert_symbol(symbol).upper()

    # 1. Commodity check (MCX)
    if any(
        clean.startswith(c) for c in ("CRUDE", "GOLD", "NATGAS", "SILVER", "COPPER", "ZINC", "ALUM")
    ):
        lot = STANDARD_LOT_SIZES.get(clean, 1)
        return "COMMODITY_MCX", lot, True

    # 2. Currency check (CDS)
    if any(clean.startswith(c) for c in ("USDINR", "EURINR", "GBPINR", "JPYINR")):
        return "CURRENCY_CDS", 1000, True

    # 3. Index Derivative check
    if clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        lot = STANDARD_LOT_SIZES.get(clean, 65)
        return "INDEX_DERIVATIVE", lot, True

    # 4. Stock F&O vs Cash Equity
    import re

    cleaned_und = re.sub(r"(?:-EQ|\.NS|\.BO)$", "", clean)
    m = re.match(r"^([A-Z0-9_\-]+?)(?:\d{2}[A-Z]{3}|\d+(?:CE|PE)|FUT|$)", cleaned_und)
    und = m.group(1).rstrip("-") if m and m.group(1) else cleaned_und

    if und in STANDARD_LOT_SIZES:
        return "STOCK_FNO", STANDARD_LOT_SIZES[und], True

    return "EQUITY_CASH", 1, False


# =============================================================================
# 5. CORE DYNAMIC RISK SCALE CLAMPING ENGINE
# =============================================================================


@dataclass
class DynamicRiskScale:
    symbol: str
    entry_price: float
    direction: str  # "BULLISH" | "BEARISH"
    clamped_stop_loss: float
    risk_points: float
    risk_pct: float
    target_1: float  # +2R Scale 50% & SL to breakeven
    target_2: float  # +4R Extension
    runner_target: float  # +6R Moonshot
    rr_ratio: float
    no_chase_boundary: float
    price_tier: str
    abs_min_risk_pts: float
    sector_category: str
    sector_beta: float
    trailing_atr_mult: float
    vix_multiplier: float
    segment: str
    lot_size: int
    is_fno: bool
    timeframe: str = "INTRADAY"
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_price": round(self.entry_price, 2),
            "direction": self.direction,
            "timeframe": self.timeframe,
            "clamped_stop_loss": round(self.clamped_stop_loss, 2),
            "risk_points": round(self.risk_points, 2),
            "risk_pct": round(self.risk_pct, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "runner_target": round(self.runner_target, 2),
            "rr_ratio": round(self.rr_ratio, 2),
            "no_chase_boundary": round(self.no_chase_boundary, 2),
            "price_tier": self.price_tier,
            "abs_min_risk_pts": self.abs_min_risk_pts,
            "sector_category": self.sector_category,
            "sector_beta": round(self.sector_beta, 2),
            "trailing_atr_mult": round(self.trailing_atr_mult, 2),
            "vix_multiplier": round(self.vix_multiplier, 2),
            "segment": self.segment,
            "lot_size": self.lot_size,
            "is_fno": self.is_fno,
            "notes": self.notes,
        }


def clamp_dynamic_risk(
    symbol: str,
    entry_price: float,
    raw_stop_loss: float,
    direction: str = "BULLISH",
    atr: Optional[float] = None,
    sector: Optional[str] = None,
    vix: Optional[float] = None,
    timeframe: Optional[str] = "INTRADAY",
) -> DynamicRiskScale:
    """
    Mathematically clamps technical stop-loss, risk points, and symmetric targets
    using the institutional 5-tier hybrid dynamic risk scaling framework.

    Timeframe-Agnostic Calibration:
      - INTRADAY (5m, 15m, 60m): Tight ATR volatility bounding (0.35x - 1.50x), 3.5% max risk cap.
      - SWING_SHORT (2-5 days): Overnight gap tolerance (0.80x - 2.20x ATR), 5.5% max risk cap, 1.5x floor.
      - SWING_MID (1-4 weeks): Multi-week structure (1.20x - 3.50x ATR), 8.5% max risk cap, 2.0x floor.
      - POSITIONAL (1-6 months): Structural trend (1.80x - 5.00x ATR), 12.0% max risk cap, 2.5x floor.

    Guarantees:
      - Nominal price tier absolute floor is respected (e.g. ₹0.10 for Suzlon, ₹2.00 for Reliance).
      - Volatility normalization dynamically calibrated to timeframe.
      - Asymmetric R:R >= 1:2.0 to Target 1, Target 2 (+4R), Runner (+6R).
      - Strict Monotonicity: SL < Entry < T1 < T2 < Runner (Long); inverted for Short.
    """
    clean_sym = canonical_alert_symbol(symbol).upper()
    is_bull = str(direction).upper() in ("BULLISH", "BUY", "LONG")
    p_entry = max(0.05, float(entry_price))

    # Timeframe profile calibration
    tf_norm = (timeframe or "INTRADAY").strip().upper()
    if tf_norm in ("DAY", "DAILY", "SWING_SHORT", "SHORT_TERM"):
        tf_canonical = "SWING_SHORT"
        atr_min_mult, atr_max_mult = 0.80, 2.20
        floor_mult = 1.5
        max_risk_cap = 0.055
    elif tf_norm in ("SWING", "SWING_MID", "WEEK", "WEEKLY", "MID_TERM"):
        tf_canonical = "SWING_MID"
        atr_min_mult, atr_max_mult = 1.20, 3.50
        floor_mult = 2.0
        max_risk_cap = 0.085
    elif tf_norm in ("MONTH", "MONTHLY", "POSITIONAL", "MULTIBAGGER", "LONG_TERM"):
        tf_canonical = "POSITIONAL"
        atr_min_mult, atr_max_mult = 1.80, 5.00
        floor_mult = 2.5
        max_risk_cap = 0.120
    else:
        tf_canonical = "INTRADAY"
        atr_min_mult, atr_max_mult = 0.35, 1.50
        floor_mult = 1.0
        max_risk_cap = 0.035

    # 1. Resolve Tier 2: Price band rule with timeframe floor multiplier
    tier_rule = resolve_price_tier(p_entry)
    abs_min_risk = round(tier_rule.abs_min_risk_pts * floor_mult, 2)

    # 2. Resolve Tier 3: Sector risk profile & beta
    sec_profile = resolve_sector_risk_profile(sector or clean_sym)

    # 3. Resolve Tier 4: Macro VIX regime multiplier
    vix_mult, vix_note = get_vix_regime_multiplier(vix)

    # 4. Resolve Tier 1 & 5: Segment and lot size
    segment_name, lot_size, is_fno = resolve_segment_profile(clean_sym)

    # 5. Raw technical structural risk distance
    raw_sl = float(raw_stop_loss)
    if is_bull:
        if raw_sl <= 0 or raw_sl >= p_entry:
            raw_risk_pts = max(abs_min_risk, p_entry * 0.012)
        else:
            raw_risk_pts = p_entry - raw_sl
    else:
        if raw_sl <= 0 or raw_sl <= p_entry:
            raw_risk_pts = max(abs_min_risk, p_entry * 0.012)
        else:
            raw_risk_pts = raw_sl - p_entry

    # 6. Volatility normalization via ATR (or dynamic price default)
    if atr and atr > 0:
        eff_atr = float(atr)
        atr_min = round(eff_atr * atr_min_mult, 2)
        atr_max = round(eff_atr * atr_max_mult, 2)
    else:
        atr_min = round(p_entry * (0.005 * floor_mult), 2)
        atr_max = round(p_entry * max_risk_cap, 2)

    # Floor and Ceiling Clamping
    lower_bound = max(abs_min_risk, atr_min)
    upper_bound = max(lower_bound * 1.5, min(p_entry * max_risk_cap, atr_max))

    clamped_risk_pts = max(lower_bound, min(raw_risk_pts, upper_bound))
    # Round to official exchange tick size: ₹0.01 for cash equities < ₹250, ₹0.05 for F&O or >= ₹250
    eff_tick = 0.05 if (is_fno or p_entry >= 250.0) else 0.01
    clamped_risk_pts = round(round(clamped_risk_pts / eff_tick) * eff_tick, 2)
    clamped_risk_pts = max(abs_min_risk, clamped_risk_pts)

    risk_pct = (clamped_risk_pts / p_entry) * 100.0

    # 7. Asymmetric Target Construction
    # T1: +2.0R (Bank 50%, trail SL to breakeven)
    # T2: +4.0R (Extension target)
    # Runner: +6.0R (Moonshot liquidity sweep)
    # No-Chase: +0.35R
    if is_bull:
        sl_final = round(p_entry - clamped_risk_pts, 2)
        t1_final = round(p_entry + (clamped_risk_pts * 2.0), 2)
        t2_final = round(p_entry + (clamped_risk_pts * 4.0), 2)
        runner_final = round(p_entry + (clamped_risk_pts * 6.0), 2)
        no_chase = round(p_entry + (clamped_risk_pts * 0.35), 2)
    else:
        sl_final = round(p_entry + clamped_risk_pts, 2)
        t1_final = round(p_entry - (clamped_risk_pts * 2.0), 2)
        t2_final = round(p_entry - (clamped_risk_pts * 4.0), 2)
        runner_final = round(p_entry - (clamped_risk_pts * 6.0), 2)
        no_chase = round(p_entry - (clamped_risk_pts * 0.35), 2)

    rr_ratio = round(abs(t1_final - p_entry) / max(0.01, clamped_risk_pts), 2)

    notes = (
        f"Dynamic Risk Clamped [{tier_rule.tier_name} | {sec_profile.category} (β={sec_profile.default_beta:.1f}) | {tf_canonical}] | "
        f"Risk: ₹{clamped_risk_pts:.2f} ({risk_pct:.2f}%) | R:R 1:{rr_ratio:.1f} | {vix_note}"
    )

    return DynamicRiskScale(
        symbol=clean_sym,
        entry_price=p_entry,
        direction="BULLISH" if is_bull else "BEARISH",
        clamped_stop_loss=sl_final,
        risk_points=clamped_risk_pts,
        risk_pct=risk_pct,
        target_1=t1_final,
        target_2=t2_final,
        runner_target=runner_final,
        rr_ratio=rr_ratio,
        no_chase_boundary=no_chase,
        price_tier=tier_rule.tier_name,
        abs_min_risk_pts=abs_min_risk,
        sector_category=sec_profile.category,
        sector_beta=sec_profile.default_beta,
        trailing_atr_mult=sec_profile.trailing_atr_multiplier,
        vix_multiplier=vix_mult,
        segment=segment_name,
        lot_size=lot_size,
        is_fno=is_fno,
        timeframe=tf_canonical,
        notes=notes,
    )


# =============================================================================
# 6. HIERARCHICAL POSITION SIZING INTEGRATION
# =============================================================================


def calculate_hierarchical_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    capital: float = 100000.0,
    target_risk_pct: float = 1.5,
    max_capital_pct: float = 25.0,
    atr: Optional[float] = None,
    sector: Optional[str] = None,
    vix: Optional[float] = None,
    circuit_distance_pct: Optional[float] = None,
    dte: Optional[int] = None,
    is_fno: Optional[bool] = None,
    timeframe: Optional[str] = "INTRADAY",
) -> dict[str, Any]:
    """
    Computes optimal shares/lots deploying the full 5-tier dynamic risk model:
      1. Clamps risk points and computes targets via clamp_dynamic_risk().
      2. Scales portfolio risk budget by VIX regime and Sector Beta (Volatility Parity).
      3. Quantizes to F&O lot sizes or Cash Equity shares.
      4. Checks SEBI circuit headroom and expiry-week physical delivery limits.
    """
    clean_sym = canonical_alert_symbol(symbol).upper()
    direction = "BULLISH" if stop_loss < entry_price else "BEARISH"

    # Step 1: Dynamic risk scale clamping
    scale = clamp_dynamic_risk(
        symbol=clean_sym,
        entry_price=entry_price,
        raw_stop_loss=stop_loss,
        direction=direction,
        atr=atr,
        sector=sector,
        vix=vix,
        timeframe=timeframe,
    )

    if is_fno is not None:
        use_fno = is_fno
        eff_lot_size = scale.lot_size if is_fno else 1
    else:
        use_fno = scale.is_fno
        eff_lot_size = scale.lot_size

    # Step 2: Volatility Risk Parity budget adjustment
    # Beta normalization: High-beta assets (beta > 1.5) receive a risk reduction
    # so their portfolio variance contribution equals standard assets.
    beta = scale.sector_beta
    beta_adjusted_risk_pct = round(target_risk_pct / max(0.65, beta * 0.8), 2)
    effective_risk_pct = round(beta_adjusted_risk_pct * scale.vix_multiplier, 2)

    # Circuit Headroom Haircut: If Upper/Lower circuit is closer than 1.5R, haircut size by 50%
    circuit_warning = ""
    if circuit_distance_pct is not None and circuit_distance_pct > 0:
        req_headroom_pct = scale.risk_pct * 1.5
        if circuit_distance_pct < req_headroom_pct:
            effective_risk_pct = round(effective_risk_pct * 0.50, 2)
            circuit_warning = f" [CIRCUIT HEADROOM WARNING: Only {circuit_distance_pct:.1f}% to circuit band; size halved]"

    # Step 3: Compute Rupee Risk Budget
    risk_budget_inr = capital * (effective_risk_pct / 100.0)

    # Step 4: Share & Lot Quantization
    raw_shares = int(risk_budget_inr / max(0.05, scale.risk_points))

    # Apply capital allocation ceiling
    max_capital_inr = capital * (max_capital_pct / 100.0)
    cap_limited_shares = int(max_capital_inr / max(0.05, scale.entry_price))
    allowed_shares = min(raw_shares, cap_limited_shares)

    if use_fno and eff_lot_size > 1:
        lots = allowed_shares // eff_lot_size
        if lots == 0 and capital >= (scale.entry_price * eff_lot_size):
            # Allow 1 lot if account can margin it
            lots = 1
        shares = lots * eff_lot_size
    else:
        lots = 1
        shares = max(1, allowed_shares)

    # Step 5: SEBI Physical Delivery check for single-stock F&O in expiry week
    physical_warning = ""
    if scale.segment == "STOCK_FNO" and dte is not None and dte <= 4:
        min_delivery_val = max(shares, eff_lot_size) * scale.entry_price
        if capital < min_delivery_val:
            physical_warning = (
                f" [SEBI PHYSICAL SETTLEMENT NOTICE: Single-stock F&O in final expiry week (DTE={dte}). "
                f"Holding overnight requires 100% margin (₹{min_delivery_val:,.1f}) vs Capital (₹{capital:,.1f})]"
            )

    allocated_capital = round(shares * scale.entry_price, 2)
    capital_pct = round((allocated_capital / capital) * 100.0, 2) if capital > 0 else 0.0
    actual_risk_inr = round(shares * scale.risk_points, 2)
    actual_risk_pct = round((actual_risk_inr / capital) * 100.0, 2) if capital > 0 else 0.0

    final_notes = f"{scale.notes}{circuit_warning}{physical_warning}"

    return {
        "symbol": clean_sym,
        "shares": shares,
        "lots": lots,
        "lot_size": eff_lot_size,
        "capital_allocated": allocated_capital,
        "capital_pct": capital_pct,
        "risk_amount": actual_risk_inr,
        "risk_pct": actual_risk_pct,
        "entry_price": scale.entry_price,
        "stop_loss": scale.clamped_stop_loss,
        "target_1": scale.target_1,
        "target_2": scale.target_2,
        "runner_target": scale.runner_target,
        "r_multiple": scale.rr_ratio,
        "no_chase_boundary": scale.no_chase_boundary,
        "price_tier": scale.price_tier,
        "sector_category": scale.sector_category,
        "segment": scale.segment,
        "timeframe": scale.timeframe,
        "notes": final_notes,
    }
