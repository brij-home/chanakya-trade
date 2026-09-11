"""
web/schemas.py
──────────────
Pydantic Request & Response Data Contracts for Web API and OpenClaw Skills.
Provides single-source-of-truth ingress validation and normalization.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class InstrumentBaseRequest(BaseModel):
    """Canonical Single Source of Truth (SSOT) request model that normalizes (symbol, exchange) at API ingress."""

    symbol: str
    exchange: str = "NSE"

    @model_validator(mode="before")
    @classmethod
    def _normalize_instrument(cls, data: Any) -> Any:
        if isinstance(data, dict):
            sym = data.get("symbol")
            exch = data.get("exchange")
            if sym:
                from analysis.universe import normalize_symbol_exchange

                clean_sym, clean_exch = normalize_symbol_exchange(sym, exch)
                data["symbol"] = clean_sym
                data["exchange"] = clean_exch
        return data


class SymbolRequest(InstrumentBaseRequest):
    pass


class BacktestRequest(InstrumentBaseRequest):
    strategy: str = "rsi"
    period: str = "1y"
    capital: Optional[float] = None
    initial_capital: Optional[float] = None
    timeframe: Optional[str] = "1d"
    risk_pct: Optional[float] = 1.0
    fast: bool = False  # True → vectorized engine (<1s, no slippage sim)


class PairsRequest(BaseModel):
    stock_a: str
    stock_b: str


class EarningsRequest(BaseModel):
    symbols: Optional[list[str]] = None


class BatchQuotesRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, description="List of symbols or instruments")
    exchange: Optional[str] = Field("NSE", description="Default exchange prefix if not provided")


class MacroRequest(BaseModel):
    symbol: Optional[str] = None


class DealsRequest(BaseModel):
    symbol: Optional[str] = None
    days: int = 5


class AnalyzeRequest(InstrumentBaseRequest):
    channel: str = "api"  # cli | electron | api | whatsapp (#179)
    force: bool = False  # True -> bypass cache and force fresh LLM run


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"  # use different IDs for separate conversations


class AlertAddRequest(InstrumentBaseRequest):
    # Price alert fields
    condition: Optional[str] = None  # ABOVE | BELOW | CROSSES
    threshold: Optional[float] = None
    # Technical alert fields
    indicator: Optional[str] = None  # RSI | MACD | ADX | ATR | SCORE
    # Conditional alert: list of conditions joined by AND
    conditions: Optional[list[dict]] = None
    # Webhook: POST here when alert fires
    webhook_url: Optional[str] = None
    # Invalidation threshold: opposite level that invalidates this alert
    invalidation_threshold: Optional[float] = None


class AlertRemoveRequest(BaseModel):
    alert_id: str


class AutoAlertsListRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limit: int = 50
    alert_type: Optional[str] = None
    stage: Optional[str] = None
    environment: Optional[str] = None
    is_invalidated: Optional[bool] = None
    target_status: Optional[str] = None
    view_mode: Optional[str] = None  # "ACTIVE" | "ARCHIVED" | "ALL"
    is_archived: Optional[bool] = None
    segment: Optional[Any] = None  # str or list[str]


class AlertPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    allowed_segments: Optional[Any] = None
    telegram: Optional[Any] = None
    ui: Optional[Any] = None
    desktop: Optional[Any] = None
    sound: Optional[Any] = None
    pause_disabled_scanners: Optional[bool] = None
    fno_chat_id: Optional[str] = None
    fno_index_chat_id: Optional[str] = None
    mcx_chat_id: Optional[str] = None
    equity_chat_id: Optional[str] = None


class AutoAlertArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alert_id: str
    archive: bool = True
    reason: Optional[str] = None


class AutoAlertCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_age_days: int = 3


class AutoAlertTestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alert_type: str = "GAMMA_BLAST"
    stage: str = "EARLY_WARNING"
    symbol: str = "RELIANCE"
    is_invalidation: bool = False


class AutoAlertTargetTestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    milestone: str = "T1"  # "T1" | "FINAL" | "TRAIL"
    should_trail: bool = True
    symbol: str = "RELIANCE"


class AlertInvalidateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alert_id: str
    reason: str = "Manually invalidated by user"


class ManualAlertTestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str = "INFY"
    condition: str = "ABOVE"
    threshold: float = 1850.0
    is_invalidation: bool = False


class HintRequest(BaseModel):
    """Mid-stream context injection (#113)."""

    stream_id: str
    hint: str


class HistoryRequest(InstrumentBaseRequest):
    interval: str = "day"  # day, 1h, 15m, 5m, 1m
    days: int = 180
    include_live: bool = True  # Include active live candle on charts


class OptionLegItem(BaseModel):
    action: str = "BUY"  # BUY | SELL
    option_type: str = "CE"  # CE | PE | STOCK
    strike: float
    premium: float
    lot_size: int = 25
    lots: int = 1


class PayoffSimRequest(BaseModel):
    symbol: str = "NIFTY"
    spot_price: float = 24000.0
    dte: int = 7
    iv: float = 14.0  # %
    iv_shock: float = 0.0  # %
    target_dte: int = 0  # 0 = expiry, > 0 = days remaining at evaluation
    legs: list[OptionLegItem]


class FlowsHistoryRequest(BaseModel):
    days: int = 15


class SectorHeatmapRequest(BaseModel):
    exchange: str = "NSE"


class PortfolioHealthRequest(BaseModel):
    portfolio: Optional[dict] = None


class TaxEstimateRequest(BaseModel):
    gross_pnl: float
    holding_period_days: int = 180
    segment: str = "EQUITY_DELIVERY"  # EQUITY_DELIVERY | EQUITY_INTRADAY | FUTURES | OPTIONS
    prior_accumulated_ltcg: float = 0.0


class DefinedRiskSpreadRequest(BaseModel):
    underlying: str = "NIFTY"
    spot_price: float = 24000.0
    strategy: str = "BULL_CALL_SPREAD"  # BULL_CALL_SPREAD | BEAR_PUT_SPREAD | BULL_PUT_SPREAD | BEAR_CALL_SPREAD | IRON_CONDOR
    iv: float = 0.15
    dte: int = 7
    num_lots: int = 1
