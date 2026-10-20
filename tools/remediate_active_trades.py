"""
tools/remediate_active_trades.py
─────────────────────────────────
Offline remediation script to audit and remediate active trades in ChanakyaTrade:
1. Safely archives stale Oct 15-16 intraday momentum setups to COMPLETED (profit) or TIME_STOP_EXIT (square-off).
2. Auto-scratches exhausted swing setups (TEXRAIL, METROPOLIS, EDELWEISS) with >75% risk budget erosion.
3. Restores MCX Multibagger by stripping erroneous intraday VWAP warning.
4. Harmonizes F&O Option plans with explicit root option_sl.
5. Inactivates broken bearish COFORGE PE setup.
6. Squares off overnight paper MIS position in RELIANCE and credits realized P&L to cash.
"""

from __future__ import annotations
import json
import pathlib
import shutil
import sys
from datetime import datetime

# UTF-8 console output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

home = pathlib.Path.home() / ".trading_platform"
aa_file = home / "auto_alerts.json"
pp_file = home / "paper_portfolio.json"

now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

print(f"[{now_iso}] Starting ChanakyaTrade Active Trades Remediation...")

# ── 1. BACKUPS ──────────────────────────────────────────────────
if aa_file.exists():
    aa_backup = aa_file.with_name(f"auto_alerts.json.bak_remediation_{now_str}")
    shutil.copy2(aa_file, aa_backup)
    print(f"  [Backup] Created {aa_backup.name}")

if pp_file.exists():
    pp_backup = pp_file.with_name(f"paper_portfolio.json.bak_remediation_{now_str}")
    shutil.copy2(pp_file, pp_backup)
    print(f"  [Backup] Created {pp_backup.name}")

# ── 2. REMEDIATE AUTO ALERTS ───────────────────────────────────
if aa_file.exists():
    alerts = json.loads(aa_file.read_text(encoding="utf-8"))
    print(f"  [AutoAlerts] Loaded {len(alerts)} alerts.")

    intraday_types = {
        "SQUEEZE_BREAKOUT",
        "SQUEEZE_BREAKDOWN",
        "ORB",
        "AFTERNOON_THRUST",
        "GAP_MOMENTUM",
    }
    stale_intraday_dates = {"2026-10-15", "2026-10-16"}

    remediated_intraday = 0
    remediated_exhausted = 0
    remediated_options = 0
    restored_multibagger = 0

    for a in alerts:
        aid = a.get("alert_id", "")
        sym = a.get("symbol", "")
        atype = a.get("alert_type", "")
        stage = a.get("stage", "")
        created_dt = a.get("created_at", "")[:10]
        plan = a.get("actionable_plan") or {}
        opt_plan = plan.get("option_plan") or {}

        # A. Clean stale intraday setups
        if atype in intraday_types and created_dt in stale_intraday_dates:
            if stage not in {
                "INVALIDATED",
                "COMPLETED",
                "TIME_STOP_EXIT",
                "EXPIRED",
                "RUNNER_EXIT",
            }:
                trg = float(a.get("trigger_level") or a.get("entry_price") or 0.0)
                ltp = float(a.get("ltp") or trg)
                direction = a.get("direction", "BULLISH")
                pnl_pct = (
                    ((ltp - trg) / trg * 100)
                    if direction == "BULLISH"
                    else ((trg - ltp) / trg * 100)
                    if trg > 0
                    else 0.0
                )

                if stage in {"T1_ACHIEVED", "DE_RISK_0_5R"} or pnl_pct >= 0.5:
                    a["stage"] = "COMPLETED"
                    a["status"] = "COMPLETED"
                    a["is_archived"] = True
                    a["archived_at"] = now_iso
                    a["archive_reason"] = f"EOD Session Close - Profit Secured (+{pnl_pct:.1f}%)"
                    a["headline"] = f"🎯 [EOD CLOSED] {sym} Profit Secured (+{pnl_pct:.1f}%)"
                else:
                    a["stage"] = "TIME_STOP_EXIT"
                    a["status"] = "TIME_STOP_EXIT"
                    a["target_status"] = "TIME_STOP_EXIT"
                    a["is_archived"] = True
                    a["archived_at"] = now_iso
                    a["archive_reason"] = "EOD Session Close - Intraday Square-off"
                    a["headline"] = f"⏱️ [EOD CLOSED] {sym} Intraday Square-Off at CMP"
                remediated_intraday += 1

        # B. Auto-scratch exhausted swing setups (>75% risk erosion)
        if aid in {
            "aa-stage-1-to-2-expansion-texrail-compounder-20261009",
            "aa-smc-spring-sweep-metropolis-pull-20261012",
            "aa-stage-1-to-2-expansion-edelweiss-pull-20261011",
        }:
            a["stage"] = "INVALIDATED"
            a["status"] = "INVALIDATED"
            a["is_invalidated"] = True
            a["is_archived"] = True
            a["archived_at"] = now_iso
            a["invalidated_at"] = now_iso
            a["invalidation_reason"] = "Risk Budget Exhaustion (>75% risk eroded) - Auto-Scratch"
            a["headline"] = f"🛑 [AUTO-SCRATCH] {sym}: Risk Budget Exhausted (Closed at Market)"
            remediated_exhausted += 1

        # C. Restore MCX Multibagger (strip erroneous intraday VWAP warning)
        if sym == "MCX" and atype == "MULTIBAGGER":
            a["stage"] = "IGNITED"
            a["status"] = "IGNITED"
            a["in_flight_warning_sent"] = False
            a["in_flight_warning_reason"] = None
            a["headline"] = "🚀 MULTIBAGGER EXPANSION: MCX Base Breakout (Target: ₹4,824.6)"
            a["summary"] = (
                "Multi-month fundamental base breakout confirmed with institutional accumulation. Target 1: ₹4,824.6 (+50%). Stop-loss: ₹2,670.4."
            )
            restored_multibagger += 1

        # D. Harmonize Option Plans (ensure option_sl exists)
        if opt_plan:
            sp = opt_plan.get("sl_premium")
            if sp is not None and not plan.get("option_sl"):
                plan["option_sl"] = f"₹{float(sp):,.2f}"
                remediated_options += 1

        # E. Invalidate COFORGE 1940 PE (spot broke above VWAP and reversed)
        if aid == "aa-asym-turtle-soup-short-coforge-20261016":
            a["stage"] = "INVALIDATED"
            a["status"] = "INVALIDATED"
            a["is_invalidated"] = True
            a["is_archived"] = True
            a["invalidated_at"] = now_iso
            a["invalidation_reason"] = "Bearish thesis invalidated: Spot broke above VWAP +1.0σ"
            a["headline"] = "🛑 [INVALIDATED] COFORGE 1940 PE: Underlying Reversed Above VWAP"

    aa_file.write_text(json.dumps(alerts, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  [AutoAlerts Remediation Summary]")
    print(f"    - Stale intraday setups closed: {remediated_intraday}")
    print(f"    - Exhausted swing trades scratched: {remediated_exhausted}")
    print(f"    - Multibagger MCX restored: {restored_multibagger}")
    print(f"    - Option plans harmonized with option_sl: {remediated_options}")

# ── 3. REMEDIATE PAPER PORTFOLIO (RELIANCE MIS) ────────────────
if pp_file.exists():
    pdata = json.loads(pp_file.read_text(encoding="utf-8"))
    positions = pdata.get("positions", {})
    if "RELIANCE" in positions:
        rpos = positions["RELIANCE"]
        if rpos.get("product") == "MIS":
            qty = rpos.get("qty", 0)
            avg_p = rpos.get("avg_price", 1239.22)
            exit_p = 1274.50  # Latest closing price
            realized_pnl = round((exit_p - avg_p) * qty, 2)
            margin_released = round(avg_p * qty * 0.20, 2)

            pdata["cash"] = round(pdata.get("cash", 200000.0) + margin_released + realized_pnl, 2)
            del positions["RELIANCE"]

            pdata.setdefault("orders", []).append(
                {
                    "order_id": f"PAPER-AUTO-EOD-REL-{now_str[-6:]}",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "transaction_type": "SELL",
                    "quantity": qty,
                    "price": exit_p,
                    "average_price": exit_p,
                    "order_type": "MARKET",
                    "product": "MIS",
                    "status": "COMPLETE",
                    "placed_at": now_iso,
                    "message": f"Auto-squareoff MIS position at session close. Realized P&L: ₹{realized_pnl:,.2f}",
                }
            )
            pp_file.write_text(json.dumps(pdata, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  [PaperPortfolio] Auto-squared off RELIANCE 60 shares MIS @ ₹{exit_p:,.2f}.")
            print(
                f"    Realized P&L: +₹{realized_pnl:,.2f} | New Available Cash: ₹{pdata['cash']:,.2f}"
            )

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}] Active trades remediation complete!")
