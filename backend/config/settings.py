"""Central configuration for the breakout detection system.

All tunable pipeline parameters live here so they are never hardcoded
inside feature engineering / labeling / inference code.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # --- Market data provider ---
    market_data_provider: str = "demo"          # "demo" | "alphavantage" | "alpaca" | "yfinance"
    alphavantage_api_key: str = ""
    alphavantage_entitlement: str = "delayed"  # "delayed" (free tier, honest default) | "realtime" (paid plan only)
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_feed: str = "iex"          # IEX is the only feed free/paper keys are entitled to (~3% of market volume)
    alpaca_bar_timeframe: str = "1Min"  # matches the live "bars" WS channel granularity (fixed at 1 min by Alpaca)
    alpaca_seed_bar_limit: int = 300    # historical bars fetched via REST to warm up indicators before going live
    yfinance_exchange_suffix: str = ".NS"   # ".NS" = NSE, ".BO" = BSE; appended if a watchlist symbol has none
    yfinance_interval: str = "5m"           # yfinance intraday granularity (1m only covers last 7 days)
    yfinance_period: str = "5d"             # how far back to pull on each fetch (5d * ~75 5m-candles/day)
    watchlist: str = "AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META,AMD,NFLX,JPM"
    refresh_interval_seconds: int = 15
    currency_symbol: str = "$"   # display only; set to "\u20b9" for INR watchlists

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

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]


settings = Settings()