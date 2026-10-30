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
    DEFAULT_US_WATCHLIST,
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
    # Both markets are served at once; the dashboard picks one per request. `market`
    # is only the DEFAULT market (what a first-time visitor sees and what training /
    # backtesting use).
    market: str = DEFAULT_MARKET                # "IN" | "US"
    exchange: str = ""                          # India only: "" -> NSE; "BSE" to switch. Ignored for US.
    market_holidays: str = ""                   # legacy: extra holidays for the DEFAULT market (ISO dates)
    market_holidays_in: str = ""                # NSE/BSE holidays, from the official exchange circular
    market_holidays_us: str = ""                # ad-hoc NYSE closures on top of the computed calendar

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
    watchlist: str = ",".join(DEFAULT_INDIA_WATCHLIST)        # India default list (env WATCHLIST kept for compatibility)
    watchlist_us: str = ",".join(DEFAULT_US_WATCHLIST)        # US default list (env WATCHLIST_US)
    # User edits (added / removed symbols) are persisted here, per market. On hosts with an
    # ephemeral disk point this at a persistent volume or edits are lost on redeploy.
    watchlist_store_path: str = ""              # "" -> backend/user_data/watchlists.json
    max_watchlist_size: int = 50                # per market; bounds provider load
    watchlist_readonly: bool = False            # true -> add/remove/reset endpoints return 403 (lock a public deployment)
    min_history_candles: int = 60               # a new symbol needs at least this many candles to be addable
    max_fetch_concurrency: int = 4              # parallel provider requests per refresh (throttle)
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

    def exchange_for(self, market_code: str) -> str:
        """Exchange for a market. EXCHANGE only applies to the market it is valid for (India)."""
        spec = get_market(market_code)
        try:
            return resolve_exchange(spec, self.exchange or None)
        except ValueError:
            return spec.default_exchange

    def holidays_for(self, market_code: str):
        code = get_market(market_code).code
        raw = {"IN": self.market_holidays_in, "US": self.market_holidays_us}[code]
        out = parse_holidays(raw)
        if code == self.market_spec.code:
            out |= parse_holidays(self.market_holidays)
        return out

    @property
    def holiday_dates(self):
        return self.holidays_for(self.market_spec.code)

    def default_watchlist(self, market_code: str) -> list[str]:
        """Provider-format default symbols for a market (the list 'Restore defaults' returns to)."""
        spec = get_market(market_code)
        raw = {"IN": self.watchlist, "US": self.watchlist_us}[spec.code]
        return parse_watchlist(raw, spec, self.exchange_for(spec.code))[0]

    @property
    def watchlist_symbols(self) -> list[str]:
        """Default watchlist of the DEFAULT market (used by training/backtesting). Per-market,
        user-editable lists are served by `backend.data.watchlist_store`."""
        return self.default_watchlist(self.market_spec.code)

    @property
    def watchlist_rejected(self) -> list[dict]:
        """Entries of the India WATCHLIST env var that are not valid NSE/BSE symbols."""
        return parse_watchlist(self.watchlist, get_market("IN"), self.exchange_for("IN"))[1]

    @property
    def config_warnings(self) -> list[str]:
        """Human-readable problems with the effective configuration (surfaced in /api/health)."""
        warnings: list[str] = []
        spec = self.market_spec
        for r in self.watchlist_rejected:
            warnings.append(f"Watchlist entry {r['symbol']} ignored: {r['reason']}")
        us_rejected = parse_watchlist(self.watchlist_us, get_market("US"), None)[1]
        for r in us_rejected:
            warnings.append(f"US watchlist entry {r['symbol']} ignored: {r['reason']}")
        legacy = [
            s.strip().upper()
            for s in self.watchlist.split(",")
            if s.strip().upper() in LEGACY_US_DEFAULT_WATCHLIST
        ]
        if legacy:
            warnings.append(
                "WATCHLIST (the India list) contains US tickers (" + ", ".join(legacy) + "). "
                "They are treated as NSE/BSE symbols and will be reported unavailable - "
                "they are never swapped for US data. Move them to WATCHLIST_US or remove them."
            )
        if self.currency_symbol and self.currency_symbol != spec.currency_symbol:
            warnings.append(
                f"CURRENCY_SYMBOL={self.currency_symbol!r} is ignored: market {spec.code} uses {spec.currency_symbol!r}."
            )
        return warnings


settings = Settings()