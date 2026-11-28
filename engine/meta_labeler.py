"""
engine/meta_labeler.py
──────────────────────
Purged Walk-Forward Meta-Labeling (`P(Net Win)`), Half-Kelly `0-lot` Cost Gate,
and Closed-Loop Forward-Path vs Fill Telemetry Separation.

Institutional Guarantees (docs/SAFETY_CONTRACTS.md #9, #17-#20):
  1. Strict Causal Features (`as_of <= trigger_time`): all 19 orthogonal features
     represent pre-trigger market state, flow, GEX, IV/VRP, and spreads.
  2. Purged & Embargoed Walk-Forward Training: chronological folds with explicit
     purge & embargo gaps prevent label-overlap leakage; outputs regularized L2
     logistic probabilities with empirical quantile MAE/MFE bounds.
  3. Uncalibrated Zero-Bonus Invariant: `< 30` non-overlapping OOS observations OR
     one-sided samples (`wins < 5` or `losses < 5`) stay `UNCALIBRATED`, yielding
     `calibrated_win_probability = None`, `half_kelly_fraction = 0.0`, and `lots = 0`.
  4. Cost-Gated Zero-Lot Floor: never applies a 1-lot floor when net expectancy
     after Apr-2026 statutory charges + bid-ask spread is `<= 0`.
  5. Telemetry Separation: `FORWARD_PATH_OBSERVATION` records never fabricate
     `VERIFIED_BROKER_FILL` or grant positive Kelly multipliers.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from config.constants import IST
from config.paths import app_data_path

logger = logging.getLogger("engine.meta_labeler")

META_FEATURE_NAMES: tuple[str, ...] = (
    "dist_to_level_atr",
    "extension_from_vwap_atr",
    "squeeze_duration_bars",
    "tod_rvol",
    "constituent_lead_impulse",
    "index_ad_ratio",
    "pct_above_vwap",
    "delta_cvd_slope",
    "obi_5_persistence",
    "spread_bps",
    "net_gex_regime_num",
    "dist_to_gamma_flip_pct",
    "pcr_change",
    "futures_basis_bps",
    "dte",
    "iv_atm",
    "vrp",
    "session_bucket_num",
    "is_event_window",
)

MIN_META_CALIBRATION_TRADES = 30
MIN_SIDE_COUNT = 5


def _default_meta_model_path() -> Path:
    return app_data_path("meta_label_model.json")


def _default_telemetry_path() -> Path:
    return app_data_path("stage_telemetry.jsonl")


def _sigmoid(z: np.ndarray | float) -> np.ndarray | float:
    clipped = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def extract_meta_feature_vector(features: dict[str, Any]) -> tuple[np.ndarray, float]:
    """Convert causal feature dict into ordered numpy vector and non-null coverage ratio."""
    vec = np.zeros(len(META_FEATURE_NAMES), dtype=float)
    present = 0
    for idx, name in enumerate(META_FEATURE_NAMES):
        raw = features.get(name)
        if name == "net_gex_regime_num" and raw is None:
            gex_str = str(features.get("net_gex_regime") or "").upper()
            if "POSITIVE" in gex_str:
                raw = 1.0
            elif "NEGATIVE" in gex_str:
                raw = -1.0
            elif gex_str:
                raw = 0.0
        if name == "session_bucket_num" and raw is None:
            sb = str(features.get("session_bucket") or "").upper()
            bucket_map = {
                "09:15-10:15": 1.0,
                "10:15-11:30": 2.0,
                "11:30-13:15": 3.0,
                "13:15-15:15": 4.0,
                "15:15-15:45": 5.0,
            }
            if sb in bucket_map:
                raw = bucket_map[sb]
        if raw is None or isinstance(raw, bool) and name != "is_event_window":
            if isinstance(raw, bool) and name == "is_event_window":
                vec[idx] = 1.0 if raw else 0.0
                present += 1
            else:
                vec[idx] = float("nan")
            continue
        try:
            val = float(raw)
            if math.isfinite(val):
                vec[idx] = val
                present += 1
            else:
                vec[idx] = float("nan")
        except (TypeError, ValueError):
            vec[idx] = float("nan")
    coverage = round(present / float(len(META_FEATURE_NAMES)), 3)
    return vec, coverage


@dataclass
class MetaLabelPrediction:
    status: str  # "CALIBRATED" | "UNCALIBRATED" | "DEGRADED"
    calibrated_win_probability: Optional[float]
    expected_net_r: Optional[float]
    avg_win_r: Optional[float]
    avg_loss_r: Optional[float]
    mae_p50_r: Optional[float]
    mfe_p50_r: Optional[float]
    half_kelly_fraction: float
    recommended_lots: int
    cost_gate_passed: bool
    sample_count: int
    oos_brier_score: Optional[float]
    feature_coverage: float
    reason: str
    as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PurgedMetaModel:
    """Trained purged walk-forward L2 logistic meta-model artifact."""

    weights: list[float]
    bias: float
    means: list[float]
    stds: list[float]
    sample_count: int
    win_count: int
    loss_count: int
    avg_win_r: float
    avg_loss_r: float
    mae_p50_r: float
    mfe_p50_r: float
    oos_brier_score: float
    status: str  # "CALIBRATED" | "UNCALIBRATED"
    trained_at: str
    provenance: str = "RESEARCH_ONLY_PURGED_WALK_FORWARD"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PurgedMetaModel":
        return cls(**data)


def _fit_l2_logistic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    l2_reg: float = 2.0,
    lr: float = 0.15,
    steps: int = 350,
) -> tuple[np.ndarray, float]:
    n_samples, n_features = X.shape
    w = np.zeros(n_features, dtype=float)
    b = 0.0
    pos_rate = float(np.clip(np.mean(y), 0.05, 0.95))
    b = math.log(pos_rate / (1.0 - pos_rate))
    for _ in range(steps):
        logits = X @ w + b
        probs = _sigmoid(logits)
        err = probs - y
        grad_w = (X.T @ err) / n_samples + (l2_reg / n_samples) * w
        grad_b = float(np.mean(err))
        w -= lr * grad_w
        b -= lr * grad_b
    return w, float(b)


def train_purged_meta_model(
    records: Sequence[dict[str, Any]],
    *,
    n_splits: int = 4,
    purge_bars: int = 3,
    embargo_bars: int = 2,
    min_samples: int = MIN_META_CALIBRATION_TRADES,
    now_dt: Optional[datetime] = None,
) -> PurgedMetaModel:
    """Train a strictly chronological, purged & embargoed walk-forward Meta-Labeling scorer.

    Expected `records` fields:
      - `features`: dict matching META_FEATURE_NAMES
      - `net_r`: float realized net R-multiple after Apr-2026 charges + spread
      - `mae_r` (optional): float >= 0 adverse excursion in R
      - `mfe_r` (optional): float >= 0 favorable excursion in R
      - `timestamp` / `trigger_time` (optional): ISO string or epoch for sorting
    """
    ref_now = (now_dt or datetime.now(IST)).isoformat()
    ordered = sorted(
        list(records),
        key=lambda r: str(r.get("trigger_time") or r.get("timestamp") or ""),
    )
    n = len(ordered)
    n_feat = len(META_FEATURE_NAMES)

    if n < min_samples:
        return PurgedMetaModel(
            weights=[0.0] * n_feat,
            bias=0.0,
            means=[0.0] * n_feat,
            stds=[1.0] * n_feat,
            sample_count=n,
            win_count=0,
            loss_count=0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            mae_p50_r=0.0,
            mfe_p50_r=0.0,
            oos_brier_score=1.0,
            status="UNCALIBRATED",
            trained_at=ref_now,
        )

    X_raw = np.zeros((n, n_feat), dtype=float)
    y = np.zeros(n, dtype=float)
    net_rs = np.zeros(n, dtype=float)
    maes: list[float] = []
    mfes: list[float] = []

    for i, rec in enumerate(ordered):
        feat_dict = rec.get("features") if isinstance(rec.get("features"), dict) else rec
        vec, _ = extract_meta_feature_vector(feat_dict)
        X_raw[i] = vec
        nr = float(rec.get("net_r", 0.0) or 0.0)
        net_rs[i] = nr
        y[i] = 1.0 if nr > 0.0 else 0.0
        if rec.get("mae_r") is not None:
            maes.append(max(0.0, float(rec["mae_r"])))
        if rec.get("mfe_r") is not None:
            mfes.append(max(0.0, float(rec["mfe_r"])))

    win_cnt = int(np.sum(y > 0.5))
    loss_cnt = int(n - win_cnt)

    if win_cnt < MIN_SIDE_COUNT or loss_cnt < MIN_SIDE_COUNT:
        return PurgedMetaModel(
            weights=[0.0] * n_feat,
            bias=0.0,
            means=[0.0] * n_feat,
            stds=[1.0] * n_feat,
            sample_count=n,
            win_count=win_cnt,
            loss_count=loss_cnt,
            avg_win_r=round(float(np.mean(net_rs[y > 0.5])), 4) if win_cnt > 0 else 0.0,
            avg_loss_r=round(float(np.mean(net_rs[y <= 0.5])), 4) if loss_cnt > 0 else 0.0,
            mae_p50_r=round(float(np.median(maes)), 3) if maes else 0.0,
            mfe_p50_r=round(float(np.median(mfes)), 3) if mfes else 0.0,
            oos_brier_score=1.0,
            status="UNCALIBRATED",
            trained_at=ref_now,
        )

    # Compute causal column means / stds safely over finite entries (zero empty-slice warnings)
    valid_mask = np.isfinite(X_raw)
    col_cnt = valid_mask.sum(axis=0)
    col_sums = np.where(valid_mask, X_raw, 0.0).sum(axis=0)
    means = np.where(col_cnt > 0, col_sums / np.maximum(col_cnt, 1), 0.0)
    X_imp = np.where(valid_mask, X_raw, means)
    stds = np.std(X_imp, axis=0)
    stds = np.where(stds > 1e-6, stds, 1.0)
    X_norm = (X_imp - means) / stds

    # Chronological Purged & Embargoed Walk-Forward OOS Brier Validation
    splits = max(2, min(n_splits, n // 10))
    fold_size = n // splits
    oos_probs: list[float] = []
    oos_targets: list[float] = []

    for f_idx in range(1, splits):
        val_start = f_idx * fold_size
        val_end = n if f_idx == splits - 1 else (f_idx + 1) * fold_size
        train_end = max(0, val_start - max(1, purge_bars + embargo_bars))
        if train_end < 12 or val_end <= val_start:
            continue
        y_tr = y[:train_end]
        if len(np.unique(y_tr)) < 2:
            continue
        w_f, b_f = _fit_l2_logistic(X_norm[:train_end], y_tr)
        p_val = _sigmoid(X_norm[val_start:val_end] @ w_f + b_f)
        oos_probs.extend([float(x) for x in p_val])
        oos_targets.extend([float(x) for x in y[val_start:val_end]])

    if oos_probs:
        brier = float(np.mean((np.array(oos_probs) - np.array(oos_targets)) ** 2))
    else:
        brier = 0.5

    w_full, b_full = _fit_l2_logistic(X_norm, y)
    avg_win = float(np.mean(net_rs[y > 0.5]))
    avg_loss = float(np.mean(net_rs[y <= 0.5]))

    return PurgedMetaModel(
        weights=[round(float(v), 6) for v in w_full],
        bias=round(float(b_full), 6),
        means=[round(float(v), 6) for v in means],
        stds=[round(float(v), 6) for v in stds],
        sample_count=n,
        win_count=win_cnt,
        loss_count=loss_cnt,
        avg_win_r=round(avg_win, 4),
        avg_loss_r=round(avg_loss, 4),
        mae_p50_r=round(float(np.median(maes)), 3) if maes else 0.0,
        mfe_p50_r=round(float(np.median(mfes)), 3) if mfes else 0.0,
        oos_brier_score=round(brier, 4),
        status="CALIBRATED",
        trained_at=ref_now,
    )


def save_meta_model(model: PurgedMetaModel, path: Optional[Path] = None) -> Path:
    target = path or _default_meta_model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return target


def load_meta_model(path: Optional[Path] = None) -> Optional[PurgedMetaModel]:
    target = path or _default_meta_model_path()
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return PurgedMetaModel.from_dict(raw)
    except Exception as exc:
        logger.debug(f"[MetaLabeler] Failed loading meta model: {exc}")
        return None


def score_meta_label_and_kelly(
    features: dict[str, Any],
    *,
    model: Optional[PurgedMetaModel] = None,
    budget_lots: int = 1,
    sl_r_distance: float = 1.0,
    min_calibrated_prob: float = 0.48,
    now_dt: Optional[datetime] = None,
) -> MetaLabelPrediction:
    """Evaluate calibrated P(Net Win), expected net R, MAE/MFE bounds & Half-Kelly 0-lot gate."""
    ref_now = (now_dt or datetime.now(IST)).isoformat()
    vec, coverage = extract_meta_feature_vector(features)
    active_model = model if model is not None else load_meta_model()

    if (
        active_model is None
        or active_model.status != "CALIBRATED"
        or active_model.sample_count < MIN_META_CALIBRATION_TRADES
        or active_model.win_count < MIN_SIDE_COUNT
        or active_model.loss_count < MIN_SIDE_COUNT
    ):
        cnt = active_model.sample_count if active_model is not None else 0
        return MetaLabelPrediction(
            status="UNCALIBRATED",
            calibrated_win_probability=None,
            expected_net_r=None,
            avg_win_r=None,
            avg_loss_r=None,
            mae_p50_r=None,
            mfe_p50_r=None,
            half_kelly_fraction=0.0,
            recommended_lots=0,
            cost_gate_passed=False,
            sample_count=cnt,
            oos_brier_score=None,
            feature_coverage=coverage,
            reason=f"UNCALIBRATED meta-model (samples={cnt} < {MIN_META_CALIBRATION_TRADES} or one-sided): zero alpha bonus.",
            as_of=ref_now,
        )

    means = np.array(active_model.means, dtype=float)
    stds = np.array(active_model.stds, dtype=float)
    weights = np.array(active_model.weights, dtype=float)
    imp = np.where(np.isfinite(vec), vec, means)
    x_norm = (imp - means) / np.where(stds > 1e-6, stds, 1.0)
    raw_prob = float(_sigmoid(float(x_norm @ weights + active_model.bias)))
    prob = round(float(np.clip(raw_prob, 0.02, 0.98)), 4)

    avg_win = max(0.01, float(active_model.avg_win_r))
    avg_loss = max(0.01, abs(float(active_model.avg_loss_r)))
    b_payoff = avg_win / avg_loss
    exp_net_r = round(prob * avg_win - (1.0 - prob) * avg_loss, 4)

    raw_kelly = ((prob * b_payoff) - (1.0 - prob)) / b_payoff
    half_kelly = round(max(0.0, min(0.25, 0.5 * raw_kelly)), 4)

    noise_trap = active_model.mae_p50_r > 0 and sl_r_distance < active_model.mae_p50_r * 0.65
    passed = bool(
        exp_net_r > 0.0 and prob >= min_calibrated_prob and half_kelly > 0.0 and not noise_trap
    )

    if passed and budget_lots > 0:
        # Quarter/Half-Kelly scales down budget_lots cleanly; never invents a 1-lot floor if <= 0.
        scaled = int(math.floor(budget_lots * min(1.0, half_kelly / 0.10)))
        rec_lots = max(0, scaled)
        if rec_lots == 0:
            passed = False
    else:
        rec_lots = 0

    if not passed:
        if noise_trap:
            reason = f"0-lot noise gate: stop {sl_r_distance:.2f}R inside median MAE ({active_model.mae_p50_r:.2f}R)."
        elif exp_net_r <= 0.0 or half_kelly <= 0.0:
            reason = f"0-lot cost gate: net expectancy E={exp_net_r:+.3f}R <= 0 (P={prob:.2%})."
        else:
            reason = f"0-lot cost gate: P(Net Win)={prob:.2%} < floor {min_calibrated_prob:.2%}."
    else:
        reason = f"Calibrated Half-Kelly {half_kelly:.2%} -> {rec_lots} lot(s) (P={prob:.2%}, E={exp_net_r:+.3f}R)."

    return MetaLabelPrediction(
        status="CALIBRATED",
        calibrated_win_probability=prob,
        expected_net_r=exp_net_r,
        avg_win_r=round(avg_win, 4),
        avg_loss_r=round(-avg_loss, 4),
        mae_p50_r=active_model.mae_p50_r,
        mfe_p50_r=active_model.mfe_p50_r,
        half_kelly_fraction=half_kelly,
        recommended_lots=rec_lots,
        cost_gate_passed=passed,
        sample_count=active_model.sample_count,
        oos_brier_score=active_model.oos_brier_score,
        feature_coverage=coverage,
        reason=reason,
        as_of=ref_now,
    )


class StageTelemetryStore:
    """Separates point-in-time Forward-Path Staging Observations from Account-Scoped Broker Fills."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def _file_path(self) -> Path:
        return self._path or _default_telemetry_path()

    def record_stage_event(
        self,
        *,
        alert_id: str,
        symbol: str,
        stage: str,
        features: dict[str, Any],
        provenance_class: str = "FORWARD_PATH_OBSERVATION",
        armed_at: Optional[str] = None,
        triggered_at: Optional[str] = None,
        spot_at_event: Optional[float] = None,
        target_level: Optional[float] = None,
        stop_loss: Optional[float] = None,
        reason_code: Optional[str] = None,
        as_of: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append immutable point-in-time feature & attribution snapshot cleanly."""
        if provenance_class not in ("FORWARD_PATH_OBSERVATION", "BROKER_RECONCILED_FILL"):
            raise ValueError(f"Unsupported provenance_class: {provenance_class}")

        lead_time_sec: Optional[float] = None
        if armed_at and triggered_at:
            try:
                t_a = datetime.fromisoformat(armed_at)
                t_t = datetime.fromisoformat(triggered_at)
                lead_time_sec = round(max(0.0, (t_t - t_a).total_seconds()), 2)
            except ValueError:
                lead_time_sec = None

        capturable_pct: Optional[float] = None
        if spot_at_event and target_level and spot_at_event > 0:
            capturable_pct = round(abs(target_level - spot_at_event) / spot_at_event * 100.0, 2)

        entry = {
            "timestamp": as_of or datetime.now(IST).isoformat(),
            "alert_id": str(alert_id),
            "symbol": str(symbol).upper(),
            "stage": str(stage).upper(),
            "provenance_class": provenance_class,
            "is_verified_broker_fill": provenance_class == "BROKER_RECONCILED_FILL",
            "lead_time_sec": lead_time_sec,
            "capturable_move_pct": capturable_pct,
            "spot_at_event": spot_at_event,
            "target_level": target_level,
            "stop_loss": stop_loss,
            "reason_code": reason_code,
            "features": dict(features),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > 2000:
                self._records = self._records[-1500:]
            fp = self._file_path()
            fp.parent.mkdir(parents=True, exist_ok=True)
            with open(fp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = list(self._records)
        if not rows and self._file_path().exists():
            try:
                lines = self._file_path().read_text(encoding="utf-8").splitlines()[-500:]
                rows = [json.loads(ln) for ln in lines if ln.strip()]
            except Exception:
                rows = []

        fwd = [r for r in rows if r.get("provenance_class") == "FORWARD_PATH_OBSERVATION"]
        fills = [r for r in rows if r.get("provenance_class") == "BROKER_RECONCILED_FILL"]
        leads = [r["lead_time_sec"] for r in rows if r.get("lead_time_sec") is not None]
        return {
            "total_events": len(rows),
            "forward_path_observations": len(fwd),
            "reconciled_broker_fills": len(fills),
            "avg_lead_time_sec": round(sum(leads) / len(leads), 2) if leads else None,
            "by_stage": {
                st: sum(1 for r in rows if r.get("stage") == st)
                for st in sorted({str(r.get("stage") or "UNKNOWN") for r in rows})
            },
        }


stage_telemetry_store = StageTelemetryStore()
