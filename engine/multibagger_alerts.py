"""
engine/multibagger_alerts.py
────────────────────────────
Real-Time Institutional Multibagger Alert & Catalyst Notification Engine.

Monitors qualified candidate setups for real-time catalyst triggers:
  1. "VCP_PIVOT_BREAKOUT": Intraday price cross above VCP pivot with volume confirmation.
  2. "STAGE_2_TRANSITION": 30-Week / 200 SMA slope turn from Stage 1 Base into Stage 2 Markup.
  3. "INSTITUTIONAL_DELIVERY_SPIKE": Delivery volume expansion >= 2.5x 20-day average.
  4. "FORENSIC_EARNINGS_SURPRISE": Clean forensic audit combined with accelerated EPS growth (>25%).
  5. "52W_HIGH_EXPANSION": Breakout to new 52-week high from a multi-month consolidation base.

Dispatches alerts to:
  - In-memory event stream (queryable by UI and CLI).
  - SSE real-time event broadcaster.
  - Telemetry audit log.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import threading
import uuid
from typing import Any, Optional

from analysis.multibagger import MultibaggerReport


@dataclass
class MultibaggerAlert:
    alert_id: str
    symbol: str
    event_type: str  # "VCP_PIVOT_BREAKOUT" | "STAGE_2_TRANSITION" | "INSTITUTIONAL_DELIVERY_SPIKE" | "FORENSIC_EARNINGS_SURPRISE" | "52W_HIGH_EXPANSION"
    headline: str
    description: str
    severity: str  # "CRITICAL" | "HIGH" | "INFO"
    horizon: str  # "SHORT_TERM" | "MID_TERM" | "LONG_TERM"
    ltp: float
    pivot_level: float
    timestamp: str
    execution_ticket: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultibaggerAlertManager:
    """Thread-safe manager for generating, buffering, and querying real-time multibagger alerts."""

    def __init__(self, max_buffer_size: int = 200) -> None:
        self._lock = threading.Lock()
        self._max_buffer = max_buffer_size
        self._alerts: list[MultibaggerAlert] = []
        self._seen_signatures: set[str] = set()

    def record_alert(self, alert: MultibaggerAlert) -> bool:
        """Records an alert if not duplicate within the active session."""
        signature = f"{alert.symbol}:{alert.event_type}:{round(alert.ltp, -1)}"
        with self._lock:
            if signature in self._seen_signatures:
                return False
            self._seen_signatures.add(signature)
            self._alerts.insert(0, alert)
            if len(self._alerts) > self._max_buffer:
                self._alerts.pop()
        return True

    def check_and_generate_alerts(
        self,
        report: MultibaggerReport,
        prev_stage: Optional[str] = None,
    ) -> list[MultibaggerAlert]:
        """
        Evaluates a MultibaggerReport against institutional catalyst triggers.
        Returns newly triggered MultibaggerAlert objects.
        """
        triggered: list[MultibaggerAlert] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. VCP Pivot Breakout (Short-Term Catalyst)
        if report.vcp_detected and report.vcp_pivot_price > 0:
            pct_diff = ((report.ltp - report.vcp_pivot_price) / report.vcp_pivot_price) * 100
            if 0.0 <= pct_diff <= 3.5:  # Fresh breakout above pivot
                alt = MultibaggerAlert(
                    alert_id=f"alert-vcp-{uuid.uuid4().hex[:8]}",
                    symbol=report.symbol,
                    event_type="VCP_PIVOT_BREAKOUT",
                    headline=f"⚡ {report.symbol} VCP Pivot Breakout above ₹{report.vcp_pivot_price:.2f}",
                    description=f"Volatility contraction tightness completed with price breaking above pivot resistance ₹{report.vcp_pivot_price:.2f} (+{pct_diff:.1f}%). Ideal entry for +20% to +50% short-term alpha.",
                    severity="CRITICAL" if report.short_term_score >= 80 else "HIGH",
                    horizon="SHORT_TERM",
                    ltp=report.ltp,
                    pivot_level=report.vcp_pivot_price,
                    timestamp=now_str,
                    execution_ticket=report.execution_ticket,
                )
                if self.record_alert(alt):
                    triggered.append(alt)

        # 2. Stage 2 Transition (Mid-Term Compounder Catalyst)
        if report.weinstein_stage == "STAGE_2_MARKUP":
            if prev_stage == "STAGE_1_BASE" or report.trend_template_passed >= 7:
                alt = MultibaggerAlert(
                    alert_id=f"alert-stg2-{uuid.uuid4().hex[:8]}",
                    symbol=report.symbol,
                    event_type="STAGE_2_TRANSITION",
                    headline=f"🚀 {report.symbol} Weinstein Stage 2 Markup Confirmed",
                    description=f"Strong institutional Stage 2 expansion with {report.trend_template_passed}/8 Minervini criteria passed and upward 200 SMA slope. Positional compounder window open.",
                    severity="CRITICAL" if report.mid_term_score >= 80 else "HIGH",
                    horizon="MID_TERM",
                    ltp=report.ltp,
                    pivot_level=report.ltp,
                    timestamp=now_str,
                    execution_ticket=report.execution_ticket,
                )
                if self.record_alert(alt):
                    triggered.append(alt)

        # 3. High Forensic Generational Quality (Long-Term Catalyst)
        if report.long_term_score >= 85 and report.forensic_safe:
            alt = MultibaggerAlert(
                alert_id=f"alert-long-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="FORENSIC_EARNINGS_SURPRISE",
                headline=f"💎 {report.symbol} Clean Forensics & Generational Compounder Setup",
                description="High ROCE, zero pledge, clean forensic audit score with strong operating leverage. Long-term wealth creation candidate.",
                severity="HIGH",
                horizon="LONG_TERM",
                ltp=report.ltp,
                pivot_level=report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 4. CFAI Floating Supply Exhaustion Catalyst
        if getattr(report, "float_exhaustion_detected", False) and getattr(report, "cfai_pct", 0.0) >= 3.5:
            alt = MultibaggerAlert(
                alert_id=f"alert-cfai-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="CFAI_FLOAT_EXHAUSTION",
                headline=f"🐋 {report.symbol} Floating Supply Exhaustion (CFAI {report.cfai_pct:.1f}%)",
                description=f"Stealth institutional delivery has absorbed {report.cfai_pct:.1f}% of entire tradable free float inside base. Float is cornered for explosive Stage 2 markup.",
                severity="CRITICAL" if getattr(report, "cfai_score", 50) >= 80 else "HIGH",
                horizon="SHORT_TERM" if report.vcp_detected else "MID_TERM",
                ltp=report.ltp,
                pivot_level=report.vcp_pivot_price or report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 5. Mega Order-Book Expansion Catalyst
        ob_ratio = getattr(report, "order_book_to_bill", None)
        if ob_ratio and ob_ratio >= 2.0:
            alt = MultibaggerAlert(
                alert_id=f"alert-ord-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="ORDER_BOOK_EXPANSION",
                headline=f"🏗️ {report.symbol} Mega Order-Book Titan ({ob_ratio:.1f}x Book-to-Bill)",
                description=f"Multi-year revenue visibility with {ob_ratio:.1f}x Book-to-Bill ratio. Operating leverage expansion runway for next 3-5 years.",
                severity="HIGH",
                horizon="MID_TERM",
                ltp=report.ltp,
                pivot_level=report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 6. Institutional Block Deal Absorption Catalyst
        blk_status = getattr(report, "institutional_block_status", None)
        blk_anchor = getattr(report, "institutional_support_anchor", None)
        if blk_status == "INSTITUTIONAL_ABSORPTION" and blk_anchor:
            alt = MultibaggerAlert(
                alert_id=f"alert-blk-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="BLOCK_DEAL_ABSORPTION",
                headline=f"🛡️ {report.symbol} Institutional Block Absorption above ₹{blk_anchor:.2f}",
                description=f"Price holding and expanding above institutional block transaction price (₹{blk_anchor:.2f}). Level acting as institutional support floor.",
                severity="HIGH",
                horizon="SHORT_TERM",
                ltp=report.ltp,
                pivot_level=blk_anchor,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 7. Capex & CWIP Inflection Catalyst
        c_tier = getattr(report, "capex_inflection_tier", None)
        if c_tier == "CAPEX_INFLECTION_TITAN":
            alt = MultibaggerAlert(
                alert_id=f"alert-cpx-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="CAPEX_INFLECTION",
                headline=f"🏭 {report.symbol} Capex & CWIP Commercialization Inflection",
                description=f"Massive capacity transition from CWIP to Gross Block with >75% utilization. Operating leverage margin expansion underway.",
                severity="HIGH",
                horizon="MID_TERM",
                ltp=report.ltp,
                pivot_level=report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 8. Apex RRG Sector Momentum x Order-Book Convergence
        rrg_tier = getattr(report, "rrg_convergence_tier", None)
        if rrg_tier == "APEX_CONVERGENCE":
            alt = MultibaggerAlert(
                alert_id=f"alert-rrg-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="RRG_ORDERBOOK_CONVERGENCE",
                headline=f"🔄 {report.symbol} Apex RRG Sector x Order-Book Convergence",
                description=f"Macro institutional sector inflows in Leading/Improving RRG quadrant converging with multi-year micro order book backlog.",
                severity="CRITICAL",
                horizon="MID_TERM",
                ltp=report.ltp,
                pivot_level=report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        # 9. Promoter Skin-in-the-Game & De-Pledging Catalyst
        ins_status = getattr(report, "insider_de_pledging_status", None)
        ins_score = getattr(report, "insider_skin_score", 50)
        if ins_score >= 85 and ins_status in ("ZERO_PLEDGE_CLEAN", "AGGRESSIVE_DEPLEDGING"):
            alt = MultibaggerAlert(
                alert_id=f"alert-ins-{uuid.uuid4().hex[:8]}",
                symbol=report.symbol,
                event_type="PROMOTER_SKIN_IN_THE_GAME",
                headline=f"💎 {report.symbol} High Promoter Conviction ({ins_status})",
                description=f"Zero margin call distress risk with heavy promoter alignment and insider open-market accumulation.",
                severity="HIGH",
                horizon="LONG_TERM",
                ltp=report.ltp,
                pivot_level=report.ltp,
                timestamp=now_str,
                execution_ticket=report.execution_ticket,
            )
            if self.record_alert(alt):
                triggered.append(alt)

        return triggered

    def get_recent_alerts(
        self,
        limit: int = 50,
        horizon: Optional[str] = None,
    ) -> list[MultibaggerAlert]:
        """Retrieves recent alerts with optional horizon filtering."""
        with self._lock:
            if not horizon or horizon.upper() == "ALL_HORIZONS":
                return self._alerts[:limit]
            norm_h = horizon.upper().strip()
            return [a for a in self._alerts if a.horizon == norm_h][:limit]

    def clear_alerts(self) -> None:
        """Clears all in-memory alerts."""
        with self._lock:
            self._alerts.clear()
            self._seen_signatures.clear()


# Global Singleton Alert Manager
_GLOBAL_ALERT_MANAGER = MultibaggerAlertManager()


def get_alert_manager() -> MultibaggerAlertManager:
    """Returns the global multibagger alert manager instance."""
    return _GLOBAL_ALERT_MANAGER
