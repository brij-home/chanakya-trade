"""
tests/test_eod_rebalancer_intermarket_and_skew.py

Comprehensive institutional test suite for:
  1. Continuous Experience Replay (EOD Postmortem -> Episodic Memory SQLite ingestion)
  2. Cross-Asset Intermarket Lead-Lag Transmission Matrix (Crude, US10Y, GIFT Nifty, DXY)
  3. SEBI Mandatory Physical Delivery & MOC Guardian Risk Engine
  4. Real-Time Options Volatility Surface & 25-Delta IV Skew / VRP
"""

from dataclasses import dataclass
from typing import Optional

from analysis.intermarket_transmission import (
    compute_symbol_transmission,
    compute_intermarket_transmission_matrix,
    MacroDriverState,
)
from engine.eod_rebalancer import (
    assess_position_delivery_risk,
    run_moc_guardian_audit,
    is_cash_settled_index,
)
from analysis.volatility_surface import (
    compute_25delta_skew_and_vrp,
)
from engine.episodic_memory import EpisodicTradeMemoryStore


@dataclass
class DummyAlert:
    alert_id: str
    symbol: str
    alert_type: str = "INTRADAY_BREAKOUT_SPARK"
    direction: str = "BULLISH"
    entry_price: float = 1000.0
    stop_loss: float = 980.0
    target_level: float = 1040.0
    target_1: float = 1040.0
    ltp: float = 1040.0
    has_triggered: bool = True
    is_invalidated: bool = False
    is_disqualified: bool = False
    target_status: str = "ACTIVE"
    stage: str = "COMPLETED"
    achieved_milestones: list[str] = None
    created_at: str = "2026-10-31 09:35:00 IST"
    holding_duration_mins: int = 40
    regime: str = "TRENDING_BULL"
    sector_tailwind: str = "LEADING"
    vpin_regime: str = "LOW_TOXICITY"

    def __post_init__(self):
        if self.achieved_milestones is None:
            self.achieved_milestones = ["T1_REACHED", "T2_REACHED"]


@dataclass
class DummyOptionContract:
    strike: float
    option_type: str
    last_price: float
    iv: Optional[float] = 16.0
    expiry: str = "2026-11-26"


# ── 1. Experience Replay (Postmortem -> Episodic Memory) ───────
def test_postmortem_to_episodic_memory_ingestion(tmp_path, monkeypatch):
    """Verifies that run_eod_alert_postmortems automatically records TradeEpisodes."""
    db_file = tmp_path / "test_episodes_eod.db"
    mem_store = EpisodicTradeMemoryStore(db_path=db_file)
    monkeypatch.setattr("engine.episodic_memory.get_episodic_memory_store", lambda: mem_store)

    from engine.alert_postmortem_runner import run_eod_alert_postmortems

    winning_alert = DummyAlert(
        alert_id="aa-spark-tata-20261031",
        symbol="TATAMOTORS",
        ltp=1045.0,
        achieved_milestones=["T1_REACHED"],
    )
    losing_alert = DummyAlert(
        alert_id="aa-spark-sbi-20261031",
        symbol="SBIN",
        entry_price=800.0,
        stop_loss=790.0,
        ltp=788.0,
        is_invalidated=True,
        achieved_milestones=[],
    )

    class DummyAutoEngine:
        def get_alerts(self):
            return [winning_alert, losing_alert]

    report = run_eod_alert_postmortems(auto_engine=DummyAutoEngine(), force=True)

    assert report["status"] == "COMPLETED"
    assert report["episodic_memories_ingested"] >= 2

    # Query episodic memory
    analogies = mem_store.query_analogous_episodes(symbol="TATAMOTORS", direction="BULLISH")
    assert analogies.sample_size >= 1
    assert any(ep["symbol"] == "TATAMOTORS" for ep in analogies.analogous_episodes)


# ── 2. Intermarket Lead-Lag Transmission ────────────────────────
def test_intermarket_transmission_crude_and_omcs():
    """Crude surge of +2.5% creates a severe bearish headwind for BPCL and bullish tailwind for ONGC."""
    mock_drivers = {
        "brent": MacroDriverState(
            key="brent",
            name="Brent Crude Oil",
            ltp=86.5,
            change_pct=2.5,
            impulse_level="SEVERE_IMPULSE",
            as_of="2026-10-31 15:30:00 IST",
        ),
        "usdinr": MacroDriverState(
            key="usdinr",
            name="USD / INR",
            ltp=84.2,
            change_pct=0.1,
            impulse_level="NORMAL",
            as_of="2026-10-31 15:30:00 IST",
        ),
    }

    bpcl_trans = compute_symbol_transmission("BPCL", drivers=mock_drivers)
    assert bpcl_trans.sector == "OMC"
    assert bpcl_trans.transmission_direction == "BEARISH_HEADWIND"
    assert bpcl_trans.net_transmission_score <= -50.0
    assert bpcl_trans.is_spillover_active is True
    assert "BPCL" in bpcl_trans.symbol

    ongc_trans = compute_symbol_transmission("ONGC", drivers=mock_drivers)
    assert ongc_trans.sector == "UPSTREAM_ENERGY"
    assert ongc_trans.transmission_direction == "BULLISH_TAILWIND"
    assert ongc_trans.net_transmission_score >= 50.0


def test_intermarket_transmission_matrix_generation():
    """Intermarket transmission matrix generates ranked list of headwinds and tailwinds."""
    matrix = compute_intermarket_transmission_matrix()
    assert matrix.timestamp is not None
    assert isinstance(matrix.macro_drivers, dict)
    assert isinstance(matrix.top_bearish_headwinds, list)
    assert isinstance(matrix.top_bullish_tailwinds, list)


# ── 3. SEBI Mandatory Physical Delivery & MOC Guardian ──────────
def test_sebi_physical_delivery_risk_stock_vs_index():
    """Index options are EXEMPT from physical delivery, while ITM stock options face escalating margin."""
    # 1. NIFTY Call (Index: 100% Cash Settled)
    idx_res = assess_position_delivery_risk(
        symbol="NIFTY 25000 CE",
        quantity=50,
        spot_price=25200.0,
        strike=25000.0,
        option_type="CE",
        days_to_expiry=1,
    )
    assert idx_res.risk_level == "EXEMPT"
    assert is_cash_settled_index("NIFTY") is True

    # 2. RELIANCE ITM Call (Stock Option: Mandatory Physical Delivery)
    stock_res = assess_position_delivery_risk(
        symbol="RELIANCE 3000 CE",
        quantity=250,
        spot_price=3050.0,
        strike=3000.0,
        option_type="CE",
        days_to_expiry=1,  # T-1: 80% delivery margin
        lot_size=250,
    )
    assert stock_res.risk_level == "CRITICAL_DELIVERY_RISK"
    assert stock_res.moneyness == "ITM"
    assert stock_res.required_margin_rate_pct == 80.0
    assert stock_res.delivery_obligation_value == (250 * 3000.0)  # ₹7,50,000


def test_moc_guardian_audit_execution():
    """MOC Guardian correctly identifies pending intraday orders and assigns session status."""
    positions = [
        {"symbol": "INFY", "quantity": 100, "product": "MIS", "last_price": 1900.0},
        {
            "symbol": "TCS 4000 CE",
            "quantity": 175,
            "product": "NRML",
            "strike": 4000.0,
            "option_type": "CE",
            "days_to_expiry": 1,
            "spot_price": 4050.0,
        },
    ]
    report = run_moc_guardian_audit(positions=positions)
    assert report.total_positions_audited >= 1
    assert report.intraday_positions_pending_close == 1
    assert report.physical_delivery_risks_detected >= 1


# ── 4. Real-Time Options 25-Delta Skew & VRP ────────────────────
def test_volatility_surface_25delta_skew_and_vrp():
    """25-Delta Skew identifies Put Skew Crash Hedging when Put IV significantly exceeds Call IV."""
    spot = 25000.0
    # Synthetic chain with elevated Put IV (22.0% Put IV vs 14.0% Call IV -> +8.0 vol pts Skew)
    mock_chain = [
        DummyOptionContract(strike=24375.0, option_type="PE", last_price=80.0, iv=22.0),
        DummyOptionContract(strike=25000.0, option_type="CE", last_price=150.0, iv=16.0),
        DummyOptionContract(strike=25000.0, option_type="PE", last_price=140.0, iv=16.0),
        DummyOptionContract(strike=25625.0, option_type="CE", last_price=70.0, iv=14.0),
    ]

    report = compute_25delta_skew_and_vrp(
        underlying="NIFTY",
        expiry="2026-11-26",
        options_chain=mock_chain,
        spot_price=spot,
        realized_vol_20d=12.0,  # ATM IV (16.0) - RV (12.0) = +4.0 VRP
    )

    assert report is not None
    assert report.underlying == "NIFTY"
    assert report.risk_reversal_skew == 8.0  # 22.0 - 14.0
    assert report.skew_regime == "PUT_SKEW_CRASH_FEAR"
    assert report.trading_edge == "THETA_HARVESTING"
    assert "Veto unhedged breakout longs" in report.actionable_directive
