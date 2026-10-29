"""Central configuration for the breakout detection system.

All tunable pipeline parameters live here so they are never hardcoded
inside feature engineering / labeling / inference code.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.config.market import (
    DEFAULT_INDIA_WATCHLIST,
    DEFAULT_MARKET,
    LEGACY_US_DEFAULT_WATCHLIST,
    MarketSpec,
    get_market,
    parse_holidays,
    parse_watchlist,
    resolve_exchange,
)

# Anchor to this file's own directory (backend/config/) rather than a
# relative ".env", which pydantic-settings would otherwise resolve
# against the process's current working directory — meaning the loaded
# .env silently changes depending on which folder you happen to run
# `uvicorn` from. This makes it always load backend/.env regardless of CWD.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore", protected_namespaces=("settings_",)
    )

    # --- Market selection (India / NSE by default) ---
    # These defaults live in CODE on purpose: backend/.env is gitignored, so a
    # deployed backend never sees a developer's local .env and falls back to
    # exactly these values.
    market: str = DEFAULT_MARKET                # "IN" | "US"
    exchange: str = ""                          # "" -> market default (NSE for IN); "BSE" to switch
    market_holidays: str = ""                   # comma-separated ISO dates, from the official exchange circular

    # --- Market data provider ---
    market_data_provider: str = "yfinance"      # "yfinance" | "demo" | "alphavantage" | "alpaca" (the last two are US-only)
    alphavantage_api_key: str = ""
    alphavantage_entitlement: str = "delayed"  # "delayed" (free tier, honest default) | "realtime" (paid plan only)
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_feed: str = "iex"          # IEX is the only feed free/paper keys are entitled to (~3% of market volume)
    alpaca_bar_timeframe: str = "1Min"  # matches the live "bars" WS channel granularity (fixed at 1 min by Alpaca)
    alpaca_seed_bar_limit: int = 300    # historical bars fetched via REST to warm up indicators before going live
    yfinance_cache_ttl_seconds: int = 30    # per (market, exchange, symbol, interval, period); limits Yahoo request rate
    yfinance_interval: str = "5m"           # yfinance intraday granularity (1m only covers last 7 days)
    yfinance_period: str = "5d"             # how far back to pull on each fetch (5d * ~75 5m-candles/day)
    # Bare symbols are qualified for the selected market/exchange (RELIANCE -> RELIANCE.NS).
    watchlist: str = ",".join(DEFAULT_INDIA_WATCHLIST)
    refresh_interval_seconds: int = 15
    currency_symbol: str = ""    # "" -> derived from the market (\u20b9 for IN). An explicit value that contradicts the market is reported in config_warnings.

    # --- Breakout label construction ---
    resistance_window: int = 20          # candles used to compute rolling resistance
    prediction_horizon: int = 10         # N future candles to check for breakout
    confirmation_threshold_pct: float = 0.015   # delta: price must exceed R by 1.5%
    volume_confirmation_multiple: float = 1.5   # relative volume must exceed this

    # --- Live alerting ---
    probability_alert_threshold: float = 0.65

    # --- Model / training ---
    model_dir: str = "model_store"
    primary_model: str = "xgboost"       # xgboost | lightgbm | random_forest | logistic_regression
    train_test_split_ratio: float = 0.8  # time-aware split point
    validation_split_ratio: float = 0.1  # taken from the tail of the train portion

    # --- Demo data ---
    demo_candle_count: int = 500
    demo_candle_interval_minutes: int = 5

    # --- derived market configuration ---
    @property
    def market_spec(self) -> MarketSpec:
        return get_market(self.market)

    @property
    def exchange_code(self) -> str:
        return resolve_exchange(self.market_spec, self.exchange or None)

    @property
    def display_currency_symbol(self) -> str:
        return self.market_spec.currency_symbol

    @property
    def holiday_dates(self):
        return parse_holidays(self.market_holidays)

    @property
    def watchlist_symbols(self) -> list[str]:
        """Provider-format symbols for the selected market/exchange (e.g. RELIANCE.NS)."""
        return parse_watchlist(self.watchlist, self.market_spec, self.exchange or None)[0]

    @property
    def watchlist_rejected(self) -> list[dict]:
        return parse_watchlist(self.watchlist, self.market_spec, self.exchange or None)[1]

    @property
    def config_warnings(self) -> list[str]:
        """Human-readable problems with the effective configuration (surfaced in /api/health)."""
        warnings: list[str] = []
        spec = self.market_spec
        for r in self.watchlist_rejected:
            warnings.append(f"Watchlist entry {r['symbol']} ignored: {r['reason']}")
        if spec.code == "IN":
            legacy = [
                s.strip().upper()
                for s in self.watchlist.split(",")
                if s.strip().upper() in LEGACY_US_DEFAULT_WATCHLIST
            ]
            if legacy:
                warnings.append(
                    "WATCHLIST contains US tickers (" + ", ".join(legacy) + ") while MARKET=IN. "
                    "They are treated as NSE/BSE symbols and will be reported unavailable - "
                    "they are never swapped for US data. Remove or replace them."
                )
        if self.currency_symbol and self.currency_symbol != spec.currency_symbol:
            warnings.append(
                f"CURRENCY_SYMBOL={self.currency_symbol!r} is ignored: market {spec.code} uses {spec.currency_symbol!r}."
            )
        return warnings


settings = Settings()