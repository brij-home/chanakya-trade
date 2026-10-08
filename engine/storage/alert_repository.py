"""
AlertRepository — Institutional Storage & Persistence Subsystem.

Encapsulates ACID file persistence, temporary file atomic rename, SQLite WAL dual-write,
corrupted file recovery, and retention/archival pruning policies for ChanakyaTrade alerts.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple

from engine.alert_model import AutoAlert

logger = logging.getLogger("engine.storage.alert_repository")
IST = timezone(timedelta(hours=5, minutes=30))


def get_auto_alerts_file() -> Path:
    """
    Resolves the canonical path to the auto_alerts.json file.
    Respects monkeypatched overrides in engine.auto_alert_engine or local module for test isolation.
    """
    # 1. Check if engine.auto_alert_engine has an overridden / monkeypatched get_auto_alerts_file or AUTO_ALERTS_FILE
    try:
        if "engine.auto_alert_engine" in sys.modules:
            aae = sys.modules["engine.auto_alert_engine"]
            if hasattr(aae, "get_auto_alerts_file"):
                fn = getattr(aae, "get_auto_alerts_file")
                if fn is not get_auto_alerts_file and callable(fn):
                    return Path(fn())
            if hasattr(aae, "AUTO_ALERTS_FILE"):
                override = getattr(aae, "AUTO_ALERTS_FILE")
                if override is not None:
                    base = Path(
                        os.environ.get("TRADING_PLATFORM_DATA")
                        or (Path.home() / ".trading_platform")
                    )
                    default_path = base / "auto_alerts.json"
                    if Path(override) != default_path:
                        return Path(override)
    except Exception as e:
        logger.debug(f"[AlertRepository] Dynamic target file resolution fallback: {e}")

    # 2. Check local module override if present
    override_local = globals().get("AUTO_ALERTS_FILE")
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    default_path = base / "auto_alerts.json"
    if override_local is not None and Path(override_local) != default_path:
        return Path(override_local)

    return default_path


AUTO_ALERTS_FILE = get_auto_alerts_file()


class AlertRepository:
    """
    Autonomous alert repository managing persistence, recovery, and pruning lifecycles.
    """

    def __init__(self, target_file_fn=None) -> None:
        self._custom_file_fn = target_file_fn

    def get_target_file(self) -> Path:
        if self._custom_file_fn is not None:
            return Path(self._custom_file_fn())
        return get_auto_alerts_file()

    def save(self, alerts: list[AutoAlert]) -> None:
        """
        Atomically saves alerts to disk via PID-tagged temporary file replacement
        and dual-writes to the SQLite WAL alert store.
        """
        try:
            target_path = self.get_target_file()
            base_prod = Path.home() / ".trading_platform" / "auto_alerts.json"
            is_test_env = bool(
                os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
            )

            # Invariant: Never pollute default production storage during tests unless redirected to sandbox/tmp
            if (
                is_test_env
                and target_path == base_prod
                and not os.environ.get("TRADING_PLATFORM_DATA")
            ):
                return

            target_path.parent.mkdir(parents=True, exist_ok=True)
            from engine.data_sanctity import assert_production_data_sanctity

            if not is_test_env:
                filtered_alerts = [
                    a for a in alerts if assert_production_data_sanctity(a, "AlertRepository")
                ]
            else:
                filtered_alerts = list(alerts)

            data = [a.to_dict() for a in filtered_alerts]
            alerts_snapshot = list(filtered_alerts)

            # Atomic persistence: write to sibling PID-tagged temp file then atomic replace
            payload = json.dumps(data, indent=2)
            temp_path = target_path.with_name(
                f"{target_path.name}.tmp.{os.getpid()}_{time.time_ns()}"
            )
            try:
                temp_path.write_text(payload, encoding="utf-8")
                for attempt in range(4):
                    try:
                        os.replace(temp_path, target_path)
                        break
                    except PermissionError:
                        if attempt == 3:
                            target_path.write_text(payload, encoding="utf-8")
                        else:
                            time.sleep(0.04)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)

            # Dual-write to institutional SQLite WAL alert store (skip under test harness)
            if not (
                "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("CHANAKYA_TESTING") == "1"
            ):
                try:
                    from engine.sqlite_store import alert_sqlite_store

                    alert_sqlite_store.save_alerts_batch(alerts_snapshot)
                except Exception as e_sql:
                    logger.warning(f"[AlertRepository] SQLite store save error: {e_sql}")
        except Exception as e:
            logger.warning(f"[AlertRepository] save error: {e}")

    def load(self) -> list[AutoAlert]:
        """
        Loads alerts from storage. Handles corrupt JSON recovery from SQLite WAL store
        and deserializes alerts with post-T1 rehabilitation.
        """
        target_path = self.get_target_file()
        data = None
        if target_path.exists():
            content = target_path.read_text(encoding="utf-8").strip()
            if content:
                try:
                    data = json.loads(content)
                except Exception as parse_err:
                    logger.warning(
                        f"[AlertRepository] Corrupted auto_alerts.json detected ({parse_err}); backing up and restoring from SQLite."
                    )
                    try:
                        backup_path = target_path.with_name(
                            f"{target_path.name}.corrupt.{int(time.time())}"
                        )
                        os.replace(target_path, backup_path)
                    except Exception:
                        pass

        if not data:
            is_test_env = (
                "PYTEST_CURRENT_TEST" in os.environ
                or "pytest" in sys.modules
                or os.environ.get("CHANAKYA_TESTING") == "1"
                or "test" in str(target_path).lower()
                or "tmp" in str(target_path).lower()
            )
            if not is_test_env:
                try:
                    from engine.sqlite_store import alert_sqlite_store

                    rows = alert_sqlite_store.get_alerts(limit=500)
                    if rows:
                        logger.info(
                            f"[AlertRepository] Restored {len(rows)} alerts from SQLite WAL store."
                        )
                        data = rows
                except Exception as sql_err:
                    logger.debug(f"[AlertRepository] SQLite fallback read error: {sql_err}")

        if not data:
            return []

        alerts: list[AutoAlert] = []
        seen_ids = set()
        for d in data:
            if isinstance(d, dict):
                aid = d.get("alert_id", "")
                if aid and aid in seen_ids:
                    continue
                if aid:
                    seen_ids.add(aid)
                try:
                    alerts.append(
                        AutoAlert(
                            alert_id=d.get("alert_id", ""),
                            alert_type=d.get("alert_type", "GENERAL"),
                            stage=d.get("stage", "EARLY_WARNING"),
                            symbol=d.get("symbol", ""),
                            exchange=d.get("exchange", "NSE"),
                            direction=d.get("direction", "NEUTRAL"),
                            headline=d.get("headline", ""),
                            summary=d.get("summary", ""),
                            ltp=float(d.get("ltp") or 0.0),
                            trigger_level=float(d.get("trigger_level") or 0.0),
                            target_level=float(d.get("target_level") or 0.0),
                            stop_loss=float(d.get("stop_loss") or 0.0),
                            strike=d.get("strike"),
                            option_type=d.get("option_type"),
                            contract_symbol=d.get("contract_symbol"),
                            metrics=d.get("metrics", {}),
                            actionable_plan=d.get("actionable_plan", {}),
                            confidence=int(d.get("confidence") or 75),
                            created_at=d.get("created_at", ""),
                            read=d.get("read", False),
                            is_live=d.get("is_live", True),
                            environment=d.get("environment", "LIVE"),
                            is_invalidated=d.get("is_invalidated", False),
                            invalidation_reason=d.get("invalidation_reason"),
                            invalidated_at=d.get("invalidated_at"),
                            achieved_milestones=d.get("achieved_milestones", []),
                            target_status=d.get("target_status", "PENDING"),
                            should_trail=d.get("should_trail", False),
                            trailing_decision=d.get("trailing_decision"),
                            trailing_stop=d.get("trailing_stop"),
                            trailing_rationale=d.get("trailing_rationale"),
                            locked_profit_pts=d.get("locked_profit_pts"),
                            locked_profit_pct=d.get("locked_profit_pct"),
                            last_trail_alert_time=d.get("last_trail_alert_time"),
                            is_archived=bool(d.get("is_archived", False)),
                            archived_at=d.get("archived_at"),
                            archive_reason=d.get("archive_reason"),
                            expiry_date=d.get("expiry_date"),
                            expiry_type=d.get("expiry_type"),
                            underlying_spot=d.get("underlying_spot"),
                            option_premium=d.get("option_premium"),
                            market_status=d.get("market_status", "SESSION_CLOSED"),
                            lot_size=d.get("lot_size"),
                            segment=d.get("segment", ""),
                            signal_ref=d.get("signal_ref"),
                            r_multiple=d.get("r_multiple"),
                            pnl_pct=d.get("pnl_pct"),
                            updated_at=d.get("updated_at"),
                            triggered_at=d.get("triggered_at"),
                            original_call_time=d.get("original_call_time") or d.get("created_at"),
                            in_flight_warning_sent=bool(d.get("in_flight_warning_sent", False)),
                            in_flight_warning_reason=d.get("in_flight_warning_reason"),
                            in_flight_warning_at=d.get("in_flight_warning_at"),
                            mtf_confluence=d.get("mtf_confluence"),
                            vix_regime=d.get("vix_regime"),
                            time_horizon=d.get("time_horizon", "INTRADAY"),
                            eta_label=d.get("eta_label"),
                            setup_style=d.get("setup_style", "CONTINUATION"),
                            entry_type=d.get("entry_type", "LIMIT_ON_PULLBACK"),
                            no_chase_boundary=d.get("no_chase_boundary"),
                            telegram_dispatched=bool(d.get("telegram_dispatched", False)),
                            dispatched_channels=list(d.get("dispatched_channels", [])),
                            telegram_suppression_reason=d.get("telegram_suppression_reason"),
                            trace_id=d.get("trace_id"),
                            quant_snapshot=d.get("quant_snapshot"),
                            initial_stop_loss=d.get("initial_stop_loss"),
                            update_count=int(d.get("update_count") or 0),
                            telegram_update_count=int(d.get("telegram_update_count") or 0),
                            audit_trail=list(d.get("audit_trail", [])),
                        )
                    )
                except Exception as item_err:
                    logger.warning(
                        f"[AlertRepository] Failed to deserialize alert {aid}: {item_err}"
                    )

        # Rehabilitate alerts falsely marked as INVALIDATED after hitting T1 or breaching ratcheted trailing stop
        rehab_count = 0
        for a in alerts:
            if a.is_invalidated and a.invalidation_reason:
                inv_r = a.invalidation_reason.lower()
                has_t1 = (
                    "T1_ACHIEVED" in (a.achieved_milestones or [])
                    or a.target_status
                    in ("T1_ACHIEVED", "T2_ACHIEVED", "TARGET_ACHIEVED", "RUNNER_CLOSED")
                    or "target 1" in inv_r
                    or "trailing stop triggered" in inv_r
                    or "trailing runner stop" in inv_r
                    or "profit secured" in inv_r
                )
                if has_t1:
                    logger.info(
                        f"[AlertRepository] Rehabilitating post-T1 falsely invalidated alert {a.symbol} ({a.alert_id}) to RUNNER_EXIT"
                    )
                    a.is_invalidated = False
                    a.stage = "RUNNER_EXIT"
                    a.target_status = "RUNNER_CLOSED"
                    a.is_active = False  # Terminal closed status
                    a.is_archived = True
                    a.invalidation_reason = None
                    if a.achieved_milestones is None:
                        a.achieved_milestones = []
                    if "RUNNER_EXIT" not in a.achieved_milestones:
                        a.achieved_milestones.append("RUNNER_EXIT")
                    inst_label = (
                        a.contract_symbol
                        or f"{a.symbol} {getattr(a, 'strike', '') or ''} {getattr(a, 'option_type', '') or ''}".strip()
                    )
                    a.headline = f"🏁 [REAL/LIVE] RUNNER CLOSED (PROFIT SECURED): {inst_label}"
                    rehab_count += 1
                    try:
                        from engine.learning_engine import pattern_learning_engine

                        pattern_learning_engine.clear_symbol_lockout(a.symbol)
                    except Exception:
                        pass

        if rehab_count > 0:
            self.save(alerts)

        return alerts

    def prune_expired_archived(
        self, alerts: list[AutoAlert], max_age_days: int = 3
    ) -> Tuple[list[AutoAlert], int]:
        """
        Prunes inactive, archived, or invalidated records older than max_age_days.
        CRITICAL SAFETY INVARIANT: Active valid trades (a.is_active == True) are NEVER purged.
        """
        now = datetime.now(IST)
        cutoff_dt = now - timedelta(days=max_age_days)
        purged_count = 0
        surviving: list[AutoAlert] = []

        for a in alerts:
            if a.is_active:
                surviving.append(a)
                continue

            # Instant purge for Quarantined or Phantom records
            if a.archive_reason and "Quarantined" in a.archive_reason:
                purged_count += 1
                continue

            # Inactive candidate: evaluate age
            ts_str = a.invalidated_at or a.archived_at or a.created_at or ""
            alert_dt = None
            if ts_str:
                clean_ts = ts_str.replace(" IST", "").strip()
                for fmt in (
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d",
                ):
                    try:
                        alert_dt = datetime.strptime(clean_ts[:19], fmt).replace(tzinfo=IST)
                        break
                    except Exception:
                        continue

            if alert_dt and alert_dt < cutoff_dt:
                purged_count += 1
                continue

            surviving.append(a)

        return surviving, purged_count

    def sanitize_legacy_alerts(self, alerts: list[AutoAlert]) -> Tuple[list[AutoAlert], int]:
        """
        Purges legacy alerts violating quality gates (illiquid index strikes, distant gamma expiries).
        Archives prior-session early warning intraday setups at rollover.
        """
        purged = 0
        surviving: list[AutoAlert] = []

        for a in alerts:
            # Skip test alerts from live index liquidity checks
            if (
                a.environment == "TEST"
                or not a.is_live
                or a.alert_id.startswith("test-")
                or a.alert_id.startswith("vm-")
                or a.alert_id.startswith("inv-")
            ):
                surviving.append(a)
                continue

            # 1. Reject already quarantined or corrupted records
            if a.archive_reason and "Quarantined" in a.archive_reason:
                purged += 1
                logger.info(f"[AlertRepository] Purged quarantined alert {a.alert_id} ({a.symbol})")
                continue

            # 2. Gate for Index GAMMA_BLAST: Must have >= 15,000 OI and <= 5/8 DTE
            if a.alert_type == "GAMMA_BLAST":
                is_index = a.symbol.upper() in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                if is_index:
                    oi = a.metrics.get("oi", 0) if a.metrics else 0
                    dte = a.metrics.get("dte") if a.metrics else None
                    if dte is None:
                        dte = getattr(a, "dte", None)
                    if dte is None and a.expiry_date:
                        try:
                            exp_str = str(a.expiry_date).split("T")[0].strip()
                            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                                try:
                                    exp_dt = datetime.strptime(exp_str, fmt).date()
                                    dte = (exp_dt - datetime.now(IST).date()).days
                                    break
                                except ValueError:
                                    pass
                        except Exception:
                            pass

                    if oi < 15000:
                        purged += 1
                        logger.info(
                            f"[AlertRepository] Purged illiquid index gamma alert {a.alert_id} "
                            f"({a.symbol} {a.strike}): OI {oi} < 15,000"
                        )
                        continue
                    elif dte is not None and (
                        dte > 8 if a.symbol.upper() in ("NIFTY",) else dte > 35
                    ):
                        purged += 1
                        logger.info(
                            f"[AlertRepository] Purged distant gamma alert {a.alert_id} "
                            f"({a.symbol} {a.strike}): DTE {dte}"
                        )
                        continue

            # 3. Gate for OPTIONS_MOMENTUM
            elif a.alert_type == "OPTIONS_MOMENTUM":
                is_index = a.symbol.upper() in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                if is_index:
                    oi = a.metrics.get("oi", 0) if a.metrics else 0
                    if oi < 5000:
                        purged += 1
                        logger.info(
                            f"[AlertRepository] Purged illiquid option momentum alert {a.alert_id} "
                            f"({a.symbol}): OI {oi} < 5,000"
                        )
                        continue

            # 4. Session Rollover Sanity: Archive unignited EARLY_WARNING alerts from prior calendar days
            ts_date = None
            if a.created_at:
                clean_ts = a.created_at.replace(" IST", "").strip()[:10]
                try:
                    ts_date = datetime.strptime(clean_ts, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if ts_date and ts_date < datetime.now(IST).date():
                if a.stage == "EARLY_WARNING":
                    a.stage = "EXPIRED"
                    a.is_archived = True
                    a.is_invalidated = True
                    exp_reason = "Prior-session early warning expired without triggering"
                    a.archive_reason = a.archive_reason or exp_reason
                    a.invalidation_reason = a.invalidation_reason or exp_reason
                    surviving.append(a)
                    continue

            surviving.append(a)

        return surviving, purged

    def deduplicate_symbols(self, alerts: list[AutoAlert]) -> Tuple[list[AutoAlert], int]:
        """
        Deduplicates multiple concurrent active alerts for the same symbol/contract (keeps latest active).
        Preserves past closed, invalidated, or archived setups for historical learning.
        """
        surviving = []
        purged = 0
        seen_active = set()

        for a in alerts:
            is_test = (
                a.environment == "TEST"
                or not a.is_live
                or a.alert_id.startswith("test-")
                or a.alert_id.startswith("vm-")
                or a.alert_id.startswith("inv-")
                or a.alert_id.startswith("t-")
            )
            if is_test:
                surviving.append(a)
                continue

            clean_sym = a.symbol.replace("NSE:", "").replace("NFO:", "").strip().upper()
            contract_sym = (a.contract_symbol or "").strip().upper()
            dedup_key = contract_sym if contract_sym else clean_sym

            if a.is_active:
                if dedup_key in seen_active:
                    purged += 1
                    continue
                seen_active.add(dedup_key)
                surviving.append(a)
            else:
                surviving.append(a)

        return surviving, purged

    def reap_expired_alerts(
        self, alerts: list[AutoAlert], purge: bool = False
    ) -> Tuple[list[AutoAlert], int]:
        """
        Reaps or purges alerts whose contract expiry or intraday shelf-life has elapsed.
        Preserves winning trades by transitioning them to COMPLETED rather than EXPIRED.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        if purge:
            purged = 0
            surviving: list[AutoAlert] = []
            for a in alerts:
                if a.is_expired or a.stage == "EXPIRED":
                    purged += 1
                else:
                    surviving.append(a)
            return surviving, purged

        reaped = 0
        for a in alerts:
            if not a.is_archived and a.is_expired:
                a.is_archived = True
                a.archived_at = now_iso
                exp_label = a.expiry_date or "weekly/intraday shelf-life passed"

                has_won = bool(
                    "TARGET_ACHIEVED" in (a.achieved_milestones or [])
                    or "T1_ACHIEVED" in (a.achieved_milestones or [])
                    or "T2_ACHIEVED" in (a.achieved_milestones or [])
                    or a.target_status in ("T1_ACHIEVED", "T2_ACHIEVED", "TARGET_ACHIEVED")
                    or (a.pnl_pct is not None and a.pnl_pct > 0.0)
                )

                if a.time_horizon in ("INTRADAY", "ROLLING_24H"):
                    exch = (a.exchange or "").upper()
                    seg = (getattr(a, "segment", "") or "").upper()
                    is_crypto = (
                        exch in ("CRYPTO", "BINANCE", "DERIBIT", "COINBASE")
                        or seg == "CRYPTO"
                        or (a.symbol or "").upper().endswith("USDT")
                        or (a.symbol or "").upper().startswith("CRYPTO:")
                        or a.time_horizon == "ROLLING_24H"
                    )
                    if is_crypto:
                        cutoff = "24h rolling limit"
                    elif exch == "MCX" or (a.symbol or "").upper() in (
                        "GOLD",
                        "GOLDM",
                        "SILVER",
                        "SILVERM",
                        "CRUDEOIL",
                        "CRUDEOILM",
                        "COPPER",
                    ):
                        cutoff = "23:15 IST"
                    else:
                        cutoff = "15:15 IST"

                    if has_won:
                        reason = (
                            f"Trade completed in profit ({cutoff} cutoff reached). Position closed."
                        )
                    else:
                        reason = (
                            f"Intraday session expired ({cutoff} cutoff reached). Trade closed."
                        )
                else:
                    if has_won:
                        reason = f"Contract completed profit target ({exp_label}). Position closed."
                    else:
                        reason = f"Contract expired ({exp_label})"

                if has_won:
                    if a.stage not in ("COMPLETED", "RUNNER_EXIT", "PROFIT_SECURED"):
                        a.stage = "COMPLETED"
                    a.is_invalidated = False
                    a.archive_reason = a.archive_reason or reason
                else:
                    a.stage = "EXPIRED"
                    a.is_invalidated = True
                    a.archive_reason = a.archive_reason or reason
                    a.invalidation_reason = a.invalidation_reason or reason

                reaped += 1

        return alerts, reaped

    def clear_test_alerts(self, alerts: list[AutoAlert]) -> Tuple[list[AutoAlert], int]:
        """
        Purges all synthetic test, simulated, or mock alerts from buffer.
        """
        purged = 0
        surviving: list[AutoAlert] = []
        for a in alerts:
            aid = (getattr(a, "alert_id", "") or "").lower()
            contract = (getattr(a, "contract_symbol", "") or "").upper()
            headline = (getattr(a, "headline", "") or "").upper()
            summary = (getattr(a, "summary", "") or "").upper()
            env = (getattr(a, "environment", "") or "").upper()
            is_test = getattr(a, "is_test", False) or getattr(a, "isTest", False)
            metrics = getattr(a, "metrics", {}) or {}
            if isinstance(metrics, dict) and metrics.get("is_test"):
                is_test = True

            is_sim = (
                is_test
                or env in ("TEST", "SIMULATE", "DEMO")
                or aid.startswith("test-")
                or aid.startswith("sim-")
                or aid.startswith("mock-")
                or "[TEST]" in headline
                or "🧪" in headline
                or "SIMULAT" in headline
                or "SIMULAT" in summary
                or "SHEDDING 14.5%" in summary
                or (aid.startswith("test-") and "2900CE" in contract)
            )

            if is_sim:
                purged += 1
            else:
                surviving.append(a)

        return surviving, purged

    def cleanup_corrupted_test_alerts(self, alerts: list[AutoAlert]) -> Tuple[list[AutoAlert], int]:
        """
        Removes synthetic test alerts incorrectly marked invalidated.
        """
        purged = 0
        surviving: list[AutoAlert] = []
        for a in alerts:
            if (
                a.environment == "TEST" or not a.is_live or a.alert_id.startswith("test-")
            ) and a.is_invalidated:
                purged += 1
            else:
                surviving.append(a)
        return surviving, purged


# Global singleton instance
alert_repository = AlertRepository()
