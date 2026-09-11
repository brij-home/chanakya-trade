"""
engine/alert_preferences.py
───────────────────────────
Institutional Alert Routing & Preferences Management.

Controls which market segments (FNO, EQUITY, COMMODITY, CURRENCY) are permitted
across delivery channels (UI Live Feed, Telegram Push, Desktop/Audio Chimes)
and background scanning engines.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from config.paths import app_data_path

logger = logging.getLogger("chanakya.alert_preferences")

CANONICAL_SEGMENTS = ("FNO_INDEX", "FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY")

SEGMENT_ALIASES: dict[str, list[str]] = {
    "FNO": ["FNO_INDEX", "FNO_STOCK"],
    "F&O": ["FNO_INDEX", "FNO_STOCK"],
    "DERIVATIVES": ["FNO_INDEX", "FNO_STOCK"],
    "FNO_INDICES": ["FNO_INDEX"],
    "FNO_INDEXES": ["FNO_INDEX"],
    "INDEX_FNO": ["FNO_INDEX"],
    "FNO_STOCKS": ["FNO_STOCK"],
    "STOCK_FNO": ["FNO_STOCK"],
}


def normalize_segment_list(raw_segments: Any) -> list[str]:
    """
    Expands aliases (e.g. FNO -> FNO_INDEX + FNO_STOCK) and normalizes to canonical segment IDs.
    If 'ALL' is present, returns all canonical segments.
    """
    if isinstance(raw_segments, str):
        if raw_segments.strip().upper() == "ALL":
            return list(CANONICAL_SEGMENTS)
        tokens = [s.strip().upper() for s in raw_segments.split(",") if s.strip()]
    elif isinstance(raw_segments, (list, set, tuple)):
        tokens = [str(s).strip().upper() for s in raw_segments if str(s).strip()]
    else:
        return list(CANONICAL_SEGMENTS)

    if "ALL" in tokens:
        return list(CANONICAL_SEGMENTS)

    result: list[str] = []
    for t in tokens:
        if t in SEGMENT_ALIASES:
            for exp in SEGMENT_ALIASES[t]:
                if exp not in result:
                    result.append(exp)
        elif t in CANONICAL_SEGMENTS:
            if t not in result:
                result.append(t)
    return result or list(CANONICAL_SEGMENTS)

MCX_COMMODITY_SYMBOLS = {
    "CRUDEOIL",
    "CRUDEOILM",
    "GOLD",
    "GOLDM",
    "GOLDGUINEA",
    "SILVER",
    "SILVERM",
    "SILVERMIC",
    "NATURALGAS",
    "COPPER",
    "ALUMINIUM",
    "ZINC",
    "LEAD",
    "NICKEL",
    "MENTHAOIL",
}

CDS_CURRENCY_SYMBOLS = {
    "USDINR",
    "EURINR",
    "GBPINR",
    "JPYINR",
    "EURUSD",
    "GBPUSD",
}

INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYAUTO",
    "NIFTYPHARMA",
    "NIFTYMETAL",
    "NIFTYENERGY",
    "SENSEX",
    "BANKEX",
    "NSEI",
    "NSEBANK",
    "CNXIT",
    "CNXAUTO",
}


def classify_alert_segment(alert: Any) -> str:
    """
    Canonical single-pass segment classifier for an alert or candidate dictionary.
    Returns one of: 'FNO_INDEX' | 'FNO_STOCK' | 'EQUITY' | 'COMMODITY' | 'CURRENCY'.
    """
    if alert is None:
        return "EQUITY"

    # Extract fields whether alert is dataclass or dict
    if isinstance(alert, dict):
        sym = str(alert.get("symbol") or "")
        exch = str(alert.get("exchange") or "").upper()
        seg = str(
            alert.get("segment")
            or (alert.get("metrics") or {}).get("segment")
            or (alert.get("actionable_plan") or {}).get("segment")
            or ""
        ).upper()
        contract = str(alert.get("contract_symbol") or alert.get("contract") or "").upper()
        op_type = str(alert.get("option_type") or "").upper()
        strike = alert.get("strike")
        expiry = alert.get("expiry_date") or alert.get("expiry")
        alt_type = str(alert.get("alert_type") or "").upper()
        deriv_type = str(alert.get("derivative_type") or "").upper()
    else:
        sym = str(getattr(alert, "symbol", "") or "")
        exch = str(getattr(alert, "exchange", "") or "").upper()
        seg = str(
            getattr(alert, "segment", None)
            or (getattr(alert, "metrics", {}) or {}).get("segment")
            or (getattr(alert, "actionable_plan", {}) or {}).get("segment")
            or ""
        ).upper()
        contract = str(getattr(alert, "contract_symbol", "") or getattr(alert, "contract", "") or "").upper()
        op_type = str(getattr(alert, "option_type", "") or "").upper()
        strike = getattr(alert, "strike", None)
        expiry = getattr(alert, "expiry_date", None) or getattr(alert, "expiry", None)
        alt_type = str(getattr(alert, "alert_type", "") or "").upper()
        deriv_type = str(getattr(alert, "derivative_type", "") or "").upper()

    clean_sym = (
        sym.replace("NSE:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("NFO:", "")
        .replace("CDS:", "")
        .replace(".NS", "")
        .replace(".BO", "")
        .replace("^", "")
        .strip()
        .upper()
    )

    # 1. Commodity (MCX)
    if (
        exch == "MCX"
        or seg in ("MCX", "COMMODITY")
        or alt_type == "COMMODITY_MOMENTUM"
        or sym.upper().startswith("MCX:")
        or clean_sym in MCX_COMMODITY_SYMBOLS
    ):
        return "COMMODITY"

    # 2. Currency (CDS)
    if (
        exch == "CDS"
        or seg in ("CDS", "CURRENCY")
        or alt_type == "CURRENCY_BREAKOUT"
        or sym.upper().startswith("CDS:")
        or clean_sym in CDS_CURRENCY_SYMBOLS
    ):
        return "CURRENCY"

    # 3. F&O / Derivatives (Split into FNO_INDEX vs FNO_STOCK)
    is_index = (
        clean_sym in INDEX_SYMBOLS
        or seg in ("INDEX", "FNO_INDEX", "INDICES")
        or clean_sym.endswith("INDEX")
    )
    is_fut = (
        "FUT" in contract
        or "FUT" in sym.upper()
        or deriv_type == "FUT"
        or alt_type == "FUTURES"
    )
    is_option = bool(op_type in ("CE", "PE") or strike or expiry)
    is_deriv_alt = alt_type in ("GAMMA_BLAST", "OPTIONS_MOMENTUM")

    if seg == "FNO_INDEX":
        return "FNO_INDEX"
    if seg == "FNO_STOCK":
        return "FNO_STOCK"

    if (
        is_index
        or is_fut
        or is_option
        or is_deriv_alt
        or seg in ("FNO", "NFO")
        or exch == "NFO"
    ):
        return "FNO_INDEX" if is_index else "FNO_STOCK"

    # 4. Default to Cash Equity
    return "EQUITY"


@dataclass
class ChannelPreferences:
    """Channel-specific alert delivery preferences."""

    enabled: bool = True
    allowed_segments: list[str] = field(
        default_factory=lambda: ["FNO_INDEX", "FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY"]
    )
    min_confidence: int = 75
    allow_early_warnings: bool = False
    allow_milestones: bool = True

    def is_segment_allowed(self, segment: str) -> bool:
        if not self.enabled:
            return False
        seg_upper = (segment or "").upper()
        allowed_upper = [s.upper() for s in self.allowed_segments]
        if "ALL" in allowed_upper:
            return True

        if seg_upper == "FNO_INDEX":
            return "FNO_INDEX" in allowed_upper or "FNO" in allowed_upper
        elif seg_upper == "FNO_STOCK":
            return "FNO_STOCK" in allowed_upper or "FNO" in allowed_upper
        elif seg_upper == "FNO":
            return any(s in allowed_upper for s in ("FNO", "FNO_INDEX", "FNO_STOCK"))
        return seg_upper in allowed_upper


@dataclass
class AlertPreferences:
    """Institutional alert routing and delivery matrix."""

    # Master allowed segments across terminal (UI default)
    allowed_segments: list[str] = field(
        default_factory=lambda: ["FNO_INDEX", "FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY"]
    )
    # Channel routing
    telegram: ChannelPreferences = field(default_factory=ChannelPreferences)
    ui: ChannelPreferences = field(default_factory=ChannelPreferences)
    desktop: ChannelPreferences = field(default_factory=ChannelPreferences)
    sound: ChannelPreferences = field(default_factory=ChannelPreferences)

    # Engine optimization: pause background scanning of segments that are disabled everywhere
    pause_disabled_scanners: bool = True

    # Dedicated F&O Telegram Destination (group / channel ID)
    fno_chat_id: Optional[str] = None

    def get_telegram_chat_id(self, segment: str = "EQUITY") -> Optional[str]:
        """Returns the target Telegram chat/group ID for a given segment."""
        seg = (segment or "").upper()
        if seg in ("FNO", "FNO_INDEX", "FNO_STOCK"):
            return (
                self.fno_chat_id
                or os.environ.get("TELEGRAM_FNO_CHAT_ID", "").strip()
                or os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
                or None
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_segments": list(self.allowed_segments),
            "telegram": asdict(self.telegram),
            "ui": asdict(self.ui),
            "desktop": asdict(self.desktop),
            "sound": asdict(self.sound),
            "pause_disabled_scanners": self.pause_disabled_scanners,
            "fno_chat_id": (
                self.fno_chat_id
                or os.environ.get("TELEGRAM_FNO_CHAT_ID", "").strip()
                or None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertPreferences:
        allowed = data.get("allowed_segments")
        if not allowed or not isinstance(allowed, list):
            allowed = ["FNO_INDEX", "FNO_STOCK", "EQUITY", "COMMODITY", "CURRENCY"]
        else:
            allowed = normalize_segment_list(allowed)

        def _make_channel(ch_data: Optional[dict[str, Any]], default_min_conf: int = 75) -> ChannelPreferences:
            if not isinstance(ch_data, dict):
                return ChannelPreferences(allowed_segments=list(allowed), min_confidence=default_min_conf)
            return ChannelPreferences(
                enabled=bool(ch_data.get("enabled", True)),
                allowed_segments=normalize_segment_list(ch_data.get("allowed_segments", allowed)),
                min_confidence=int(ch_data.get("min_confidence", default_min_conf)),
                allow_early_warnings=bool(ch_data.get("allow_early_warnings", False)),
                allow_milestones=bool(ch_data.get("allow_milestones", True)),
            )

        return cls(
            allowed_segments=list(allowed),
            telegram=_make_channel(data.get("telegram"), default_min_conf=80),
            ui=_make_channel(data.get("ui"), default_min_conf=75),
            desktop=_make_channel(data.get("desktop"), default_min_conf=80),
            sound=_make_channel(data.get("sound"), default_min_conf=80),
            pause_disabled_scanners=bool(data.get("pause_disabled_scanners", True)),
            fno_chat_id=data.get("fno_chat_id"),
        )


class AlertPreferencesManager:
    """Thread-safe persistent alert preferences manager."""

    _instance: Optional[AlertPreferencesManager] = None
    _lock = threading.RLock()

    def __new__(cls) -> AlertPreferencesManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._pref_file: Path = app_data_path("alert_preferences.json")
        self._preferences: AlertPreferences = AlertPreferences()
        self._load()

    def _load(self) -> None:
        """Loads preferences from disk, or initializes defaults."""
        with self._lock:
            try:
                if self._pref_file.exists():
                    text = self._pref_file.read_text(encoding="utf-8")
                    data = json.loads(text)
                    if isinstance(data, dict):
                        self._preferences = AlertPreferences.from_dict(data)
                        return
            except Exception as e:
                logger.warning(f"Error loading alert preferences from {self._pref_file}: {e}")
            self._preferences = AlertPreferences()

    def _save(self) -> None:
        """Persists current preferences to disk safely."""
        with self._lock:
            try:
                self._pref_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = self._pref_file.with_suffix(".tmp")
                tmp_file.write_text(
                    json.dumps(self._preferences.to_dict(), indent=2),
                    encoding="utf-8",
                )
                tmp_file.replace(self._pref_file)
            except Exception as e:
                logger.error(f"Failed to persist alert preferences to {self._pref_file}: {e}")

    def get_preferences(self) -> dict[str, Any]:
        """Returns current alert preferences as a serializable dict."""
        with self._lock:
            return self._preferences.to_dict()

    def update_preferences(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Updates preferences from a partial or full dictionary and persists them.
        Accepts:
          - allowed_segments: list of segment strings (e.g. ['FNO', 'EQUITY'] or ['ALL'])
          - telegram: dict of channel settings or list of segments
          - ui: dict of channel settings or list of segments
          - desktop: dict of channel settings
          - sound: dict of channel settings
          - pause_disabled_scanners: bool
        """
        with self._lock:
            # 1. Master allowed segments
            if "allowed_segments" in data:
                self._preferences.allowed_segments = normalize_segment_list(data["allowed_segments"])

            # 2. Channel updates
            for ch_name in ("telegram", "ui", "desktop", "sound"):
                if ch_name in data:
                    ch_val = data[ch_name]
                    target_ch: ChannelPreferences = getattr(self._preferences, ch_name)
                    if isinstance(ch_val, dict):
                        if "enabled" in ch_val:
                            target_ch.enabled = bool(ch_val["enabled"])
                        if "allowed_segments" in ch_val:
                            target_ch.allowed_segments = normalize_segment_list(ch_val["allowed_segments"])
                        if "min_confidence" in ch_val:
                            target_ch.min_confidence = int(ch_val["min_confidence"])
                        if "allow_early_warnings" in ch_val:
                            target_ch.allow_early_warnings = bool(ch_val["allow_early_warnings"])
                        if "allow_milestones" in ch_val:
                            target_ch.allow_milestones = bool(ch_val["allow_milestones"])
                    elif isinstance(ch_val, (list, str)):
                        target_ch.allowed_segments = normalize_segment_list(ch_val)

            if "pause_disabled_scanners" in data:
                self._preferences.pause_disabled_scanners = bool(data["pause_disabled_scanners"])

            if "fno_chat_id" in data:
                val = data["fno_chat_id"]
                self._preferences.fno_chat_id = str(val).strip() if val else None

            self._save()
            return self._preferences.to_dict()

    def set_allowed_segments(
        self,
        segments: list[str] | str,
        channel: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Convenience method to set allowed segments for a specific channel or globally.
        If channel is None, updates master + mirrors to telegram and ui.
        """
        valid_segs = normalize_segment_list(segments)

        if channel:
            ch_clean = channel.lower().strip()
            return self.update_preferences({ch_clean: {"allowed_segments": valid_segs}})

        return self.update_preferences({
            "allowed_segments": valid_segs,
            "telegram": {"allowed_segments": valid_segs},
            "ui": {"allowed_segments": valid_segs},
            "desktop": {"allowed_segments": valid_segs},
            "sound": {"allowed_segments": valid_segs},
        })

    def is_segment_allowed(self, segment: str, channel: str = "ui") -> bool:
        """Checks whether a specific segment is allowed for a given channel."""
        with self._lock:
            seg_upper = (segment or "").upper()
            if channel == "telegram":
                return self._preferences.telegram.is_segment_allowed(seg_upper)
            elif channel == "desktop":
                return self._preferences.desktop.is_segment_allowed(seg_upper)
            elif channel == "sound":
                return self._preferences.sound.is_segment_allowed(seg_upper)
            # Default UI channel
            return self._preferences.ui.is_segment_allowed(seg_upper)

    def is_alert_allowed(self, alert: Any, channel: str = "ui") -> bool:
        """
        Evaluates whether an alert is permitted to be dispatched/displayed on a given channel.
        Checks segment membership, confidence threshold, and lifecycle stage rules.
        """
        with self._lock:
            seg = classify_alert_segment(alert)
            ch_pref = getattr(self._preferences, channel, self._preferences.ui)

            if not ch_pref.enabled:
                return False

            if not ch_pref.is_segment_allowed(seg):
                return False

            # Extract confidence and stage
            if isinstance(alert, dict):
                conf = int(alert.get("confidence") or alert.get("conviction_score") or 75)
                stage = str(alert.get("stage") or "").upper()
                is_invalidated = bool(alert.get("is_invalidated") or stage == "INVALIDATED")
                target_status = str(alert.get("target_status") or "").upper()
            else:
                conf = int(getattr(alert, "confidence", 75) or getattr(alert, "conviction_score", 75) or 75)
                stage = str(getattr(alert, "stage", "") or "").upper()
                is_invalidated = bool(getattr(alert, "is_invalidated", False) or stage == "INVALIDATED")
                target_status = str(getattr(alert, "target_status", "") or "").upper()

            is_milestone = (
                is_invalidated
                or stage in ("T1_ACHIEVED", "TARGET_ACHIEVED", "TRAILING_UPDATE")
                or "T1" in target_status
                or "TARGET" in target_status
            )

            # Milestones check
            if is_milestone:
                return ch_pref.allow_milestones

            # Early warning check
            if stage == "EARLY_WARNING" and not ch_pref.allow_early_warnings:
                # Early warnings require explicit opt-in unless confidence is >= 90
                if conf < 90:
                    return False

            # General confidence threshold
            if conf < ch_pref.min_confidence:
                return False

            return True

    def is_segment_globally_disabled(self, segment: str) -> bool:
        """
        Returns True if a segment is disabled across ALL channels (UI, Telegram, Desktop).
        Used by the background scanner to skip polling loops entirely if configured.
        """
        with self._lock:
            if not self._preferences.pause_disabled_scanners:
                return False
            seg_upper = segment.upper()
            ui_ok = self._preferences.ui.is_segment_allowed(seg_upper)
            tg_ok = self._preferences.telegram.is_segment_allowed(seg_upper)
            desk_ok = self._preferences.desktop.is_segment_allowed(seg_upper)
            return not (ui_ok or tg_ok or desk_ok)


    def get_telegram_chat_id(self, segment: str = "EQUITY") -> Optional[str]:
        """Returns the target Telegram chat ID for a given segment."""
        with self._lock:
            return self._preferences.get_telegram_chat_id(segment)


# Module-level singleton
alert_preferences = AlertPreferencesManager()
