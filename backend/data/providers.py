"""Market data provider abstraction.

Design: a single `MarketDataProvider` interface so the rest of the system
never cares whether data is coming from demo/simulated candles or a real
API. Swapping providers means adding a new class + one line in
`get_provider()`.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from backend.config.market import InvalidSymbolError, MarketSpec, qualify_symbol
from backend.config.settings import settings

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class ProviderUnavailableError(RuntimeError):
    """Raised when a live provider cannot currently return data (rate limit,
    network error, invalid key, invalid symbol, etc). Callers must NOT
    silently substitute demo data when this is raised — surface the failure
    so the UI can show LIVE DATA UNAVAILABLE instead."""


class MarketDataProvider(ABC):
    """Abstract base for anything that can return OHLCV candles."""

    # one of: "demo" | "live" | "delayed" | "unavailable"
    is_live: bool = False
    data_status: str = "demo"
    name: str = "abstract"
    # Markets this provider can serve. A provider that does not list the
    # selected market must not be used for it (see get_provider()).
    supported_markets: tuple = ("IN", "US")

    @abstractmethod
    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        """Return a DataFrame with OHLCV_COLUMNS, sorted ascending by time."""
        raise NotImplementedError

    @abstractmethod
    def get_latest_candle(self, symbol: str) -> pd.Series:
        """Return the single most recent candle for `symbol`."""
        raise NotImplementedError


class DemoDataProvider(MarketDataProvider):
    """Deterministic-but-random synthetic OHLCV generator.

    Uses a per-symbol seeded random walk with occasional drift/volatility
    regimes so the resulting series contains realistic-looking breakout
    setups (consolidation followed by a volume-backed push through
    resistance) without ever claiming to be real market data.
    """

    is_live = False
    data_status = "demo"
    name = "demo"
    feed = "simulated"

    def __init__(self) -> None:
        self._cache: dict[str, pd.DataFrame] = {}

    def _seed_for(self, symbol: str) -> int:
        return abs(hash(symbol)) % (2**32)

    def _generate(self, symbol: str, n_candles: int) -> pd.DataFrame:
        rng = np.random.default_rng(self._seed_for(symbol))
        interval = timedelta(minutes=settings.demo_candle_interval_minutes)
        start = datetime.now(timezone.utc) - interval * n_candles

        price = float(rng.uniform(50, 400))
        closes = []
        vols = []
        base_vol = rng.uniform(500_000, 3_000_000)

        # regime-switching random walk: alternates consolidation / trend / breakout push
        regime_len = max(15, n_candles // 12)
        for i in range(n_candles):
            regime = (i // regime_len) % 3
            if regime == 0:  # consolidation - low drift, low vol
                drift, vol_mult = 0.0, 1.0
                sigma = 0.003
            elif regime == 1:  # trend - directional drift
                drift = rng.choice([-1, 1]) * 0.0015
                sigma = 0.004
                vol_mult = 1.2
            else:  # breakout push - strong drift + volume spike near the end
                drift = 0.004
                sigma = 0.006
                vol_mult = 2.2 if i % regime_len > regime_len - 4 else 1.3

            shock = rng.normal(drift, sigma)
            price = max(1.0, price * (1 + shock))
            closes.append(price)
            vols.append(max(1000, base_vol * vol_mult * rng.uniform(0.6, 1.4)))

        closes = np.array(closes)
        opens = np.empty_like(closes)
        opens[0] = closes[0] * (1 - 0.001)
        opens[1:] = closes[:-1]

        highs = np.maximum(opens, closes) * (1 + rng.uniform(0.0005, 0.006, n_candles))
        lows = np.minimum(opens, closes) * (1 - rng.uniform(0.0005, 0.006, n_candles))

        timestamps = [start + interval * i for i in range(n_candles)]

        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.array(vols, dtype=float),
            }
        )
        return df

    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        if symbol not in self._cache or len(self._cache[symbol]) < limit:
            self._cache[symbol] = self._generate(symbol, max(limit, settings.demo_candle_count))
        return self._cache[symbol].tail(limit).reset_index(drop=True)

    def get_latest_candle(self, symbol: str) -> pd.Series:
        df = self.get_ohlcv(symbol, limit=settings.demo_candle_count)
        last = df.iloc[-1].copy()

        # simulate the "next tick" by advancing the walk by one candle so
        # repeated calls behave like a live feed rather than a static replay
        rng = np.random.default_rng()
        shock = rng.normal(0.0002, 0.003)
        new_close = max(1.0, last["close"] * (1 + shock))
        new_row = pd.DataFrame(
            [
                {
                    "timestamp": last["timestamp"] + timedelta(minutes=settings.demo_candle_interval_minutes),
                    "open": last["close"],
                    "high": max(last["close"], new_close) * (1 + rng.uniform(0.0005, 0.003)),
                    "low": min(last["close"], new_close) * (1 - rng.uniform(0.0005, 0.003)),
                    "close": new_close,
                    "volume": max(1000, last["volume"] * rng.uniform(0.7, 1.5)),
                }
            ]
        )
        self._cache[symbol] = pd.concat([self._cache[symbol], new_row], ignore_index=True)
        return new_row.iloc[0]


class AlphaVantageProvider(MarketDataProvider):
    """Live provider using Alpha Vantage's intraday endpoint.

    Honesty note: Alpha Vantage's free-tier API key does NOT carry a
    real-time entitlement — intraday data is end-of-day/delayed unless the
    caller has a paid "realtime" entitlement on their key. We therefore
    default `data_status` to "delayed" and only claim "live" if the caller
    explicitly configures `alphavantage_entitlement=realtime` (a paid plan).
    Never silently upgrade the label based on hope.
    """

    is_live = True  # kept for backward-compat with existing UI checks
    name = "alphavantage"
    supported_markets = ("US",)   # Indian coverage is not verified for this integration

    def __init__(self, api_key: str, entitlement: str = "delayed") -> None:
        if not api_key:
            raise ValueError("AlphaVantageProvider requires an API key")
        self.api_key = api_key
        self.entitlement = entitlement if entitlement in ("delayed", "realtime") else "delayed"
        self.data_status = "live" if self.entitlement == "realtime" else "delayed"
        self.is_live = self.entitlement == "realtime"
        self._last_latency_ms: Optional[float] = None

    def _fetch(self, symbol: str) -> pd.DataFrame:
        import time

        import requests  # local import: optional dependency path

        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": "5min",
            "outputsize": "compact",
            "apikey": self.api_key,
        }
        if self.entitlement == "realtime":
            params["entitlement"] = "realtime"

        t0 = time.monotonic()
        try:
            resp = requests.get(url, params=params, timeout=10)
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"Alpha Vantage network error for {symbol}: {exc}") from exc
        self._last_latency_ms = (time.monotonic() - t0) * 1000

        if resp.status_code != 200:
            raise ProviderUnavailableError(f"Alpha Vantage HTTP {resp.status_code} for {symbol}")

        payload = resp.json()

        # Alpha Vantage signals rate limiting / plan restrictions via these
        # keys rather than an HTTP error status — must check explicitly.
        if "Note" in payload:
            raise ProviderUnavailableError(f"Alpha Vantage rate limit hit: {payload['Note']}")
        if "Information" in payload:
            raise ProviderUnavailableError(f"Alpha Vantage plan/rate limit: {payload['Information']}")
        if "Error Message" in payload:
            raise ProviderUnavailableError(f"Alpha Vantage error for {symbol}: {payload['Error Message']}")

        series_key = next((k for k in payload if "Time Series" in k), None)
        if not series_key:
            raise ProviderUnavailableError(f"Unexpected Alpha Vantage response for {symbol}: {payload}")

        rows = []
        for ts, ohlcv in payload[series_key].items():
            rows.append(
                {
                    "timestamp": pd.to_datetime(ts, utc=True),
                    "open": float(ohlcv["1. open"]),
                    "high": float(ohlcv["2. high"]),
                    "low": float(ohlcv["3. low"]),
                    "close": float(ohlcv["4. close"]),
                    "volume": float(ohlcv["5. volume"]),
                }
            )
        if not rows:
            raise ProviderUnavailableError(f"Alpha Vantage returned no candles for {symbol}")
        df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return df

    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        df = self._fetch(symbol)
        return df.tail(limit).reset_index(drop=True)

    def get_latest_candle(self, symbol: str) -> pd.Series:
        df = self._fetch(symbol)
        return df.iloc[-1]


class AlpacaProvider(MarketDataProvider):
    """Live provider using Alpaca's IEX real-time bar WebSocket, seeded with
    historical bars via Alpaca's REST bars endpoint.

    Honesty notes:
    - IEX is a single exchange (~2-3% of US equity volume), NOT the
      consolidated tape. `feed` is always reported as "iex" so the UI can
      show "LIVE • IEX" rather than implying full-market coverage.
    - `data_status` never silently becomes "demo". If credentials are
      missing/invalid or the socket cannot authenticate, every read raises
      `ProviderUnavailableError` so the caller (inference pipeline) marks
      that symbol/cycle as unavailable instead of guessing.
    - The WS "bars" channel emits fixed 1-minute aggregated bars (Alpaca
      does not offer a configurable live aggregation window), so
      `alpaca_bar_timeframe` is 1Min for both the REST seed and the live
      feed to keep the series consistent.
    """

    name = "alpaca"
    feed = "iex"
    supported_markets = ("US",)   # Alpaca market data covers US equities only

    def __init__(self, api_key: str, api_secret: str, symbols: list[str]) -> None:
        import threading

        if not api_key or not api_secret:
            raise ValueError("AlpacaProvider requires both ALPACA_API_KEY and ALPACA_API_SECRET")

        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = [s.upper() for s in symbols]

        self._lock = threading.Lock()
        self._buffers: dict[str, pd.DataFrame] = {}
        self._seeded = False
        self._seed_error: Optional[str] = None
        self._ws_state = "connecting"   # connecting | authenticated | auth_failed | disconnected
        self._ws_error: Optional[str] = None
        self._last_bar_at: Optional[datetime] = None
        self._last_latency_ms: Optional[float] = None
        self.is_live = False  # flips true only once WS is authenticated+subscribed

        self._seed_historical()
        self._start_ws_thread()

    # --- status -----------------------------------------------------
    @property
    def data_status(self) -> str:
        if self._seed_error or self._ws_state == "auth_failed":
            return "unavailable"
        if not self._seeded:
            return "unavailable"
        if self._ws_state == "authenticated":
            return "live"
        # seeded historical data exists but the live socket isn't up yet
        return "delayed"

    def status_detail(self) -> dict:
        return {
            "provider": self.name,
            "feed": self.feed,
            "ws_state": self._ws_state,
            "ws_error": self._ws_error,
            "seed_error": self._seed_error,
            "last_bar_at": self._last_bar_at.isoformat() if self._last_bar_at else None,
        }

    # --- REST historical seed ----------------------------------------
    def _seed_historical(self) -> None:
        import requests

        url = "https://data.alpaca.markets/v2/stocks/bars"
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}
        params = {
            "symbols": ",".join(self.symbols),
            "timeframe": settings.alpaca_bar_timeframe,
            "limit": settings.alpaca_seed_bar_limit,
            "feed": self.feed,
            "adjustment": "raw",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            self._seed_error = f"network error fetching historical bars: {exc}"
            logger.error("Alpaca REST seed failed: %s", self._seed_error)
            return

        if resp.status_code == 401 or resp.status_code == 403:
            self._seed_error = f"invalid Alpaca credentials (HTTP {resp.status_code})"
            logger.error(self._seed_error)
            return
        if resp.status_code != 200:
            self._seed_error = f"Alpaca REST HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error(self._seed_error)
            return

        payload = resp.json()
        bars_by_symbol = payload.get("bars", {})
        with self._lock:
            for sym in self.symbols:
                rows = bars_by_symbol.get(sym) or []
                if not rows:
                    continue
                df = pd.DataFrame(
                    [
                        {
                            "timestamp": pd.to_datetime(b["t"], utc=True),
                            "open": float(b["o"]),
                            "high": float(b["h"]),
                            "low": float(b["l"]),
                            "close": float(b["c"]),
                            "volume": float(b["v"]),
                        }
                        for b in rows
                    ]
                ).sort_values("timestamp").reset_index(drop=True)
                self._buffers[sym] = df
        if not self._buffers:
            self._seed_error = "Alpaca returned no historical bars for any watchlist symbol"
            logger.error(self._seed_error)
        self._seeded = bool(self._buffers)

    # --- live WebSocket ------------------------------------------------
    def _start_ws_thread(self) -> None:
        import threading

        if self._seed_error:
            # don't bother opening a socket if credentials are already known-bad
            self._ws_state = "auth_failed"
            self._ws_error = self._seed_error
            return
        t = threading.Thread(target=self._ws_run_forever, daemon=True)
        t.start()

    def _ws_run_forever(self) -> None:
        import json
        import time

        import websocket

        url = f"wss://stream.data.alpaca.markets/v2/{self.feed}"
        backoff = 2

        while True:
            try:
                ws = websocket.create_connection(url, timeout=10)
                ws.recv()  # initial "connected" message
                ws.send(json.dumps({"action": "auth", "key": self.api_key, "secret": self.api_secret}))
                auth_resp = json.loads(ws.recv())
                auth_ok = any(m.get("T") == "success" and m.get("msg") == "authenticated" for m in auth_resp)
                if not auth_ok:
                    self._ws_state = "auth_failed"
                    self._ws_error = f"Alpaca WS auth rejected: {auth_resp}"
                    logger.error(self._ws_error)
                    return  # invalid creds won't fix themselves on retry

                ws.send(json.dumps({"action": "subscribe", "bars": self.symbols}))
                sub_resp = json.loads(ws.recv())
                logger.info("Alpaca WS subscribed: %s", sub_resp)

                self._ws_state = "authenticated"
                self._ws_error = None
                self.is_live = True
                backoff = 2

                while True:
                    t0 = time.monotonic()
                    raw = ws.recv()
                    self._last_latency_ms = (time.monotonic() - t0) * 1000
                    for msg in json.loads(raw):
                        if msg.get("T") == "b":
                            self._on_bar(msg)

            except Exception as exc:  # network drop, decode error, etc.
                self._ws_state = "disconnected"
                self._ws_error = str(exc)
                self.is_live = False
                logger.warning("Alpaca WS disconnected, retrying in %ss: %s", backoff, exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _on_bar(self, msg: dict) -> None:
        sym = msg.get("S")
        if sym not in self.symbols:
            return
        row = pd.DataFrame(
            [
                {
                    "timestamp": pd.to_datetime(msg["t"], utc=True),
                    "open": float(msg["o"]),
                    "high": float(msg["h"]),
                    "low": float(msg["l"]),
                    "close": float(msg["c"]),
                    "volume": float(msg["v"]),
                }
            ]
        )
        with self._lock:
            existing = self._buffers.get(sym)
            if existing is None or existing.empty:
                self._buffers[sym] = row
            else:
                # replace if same timestamp (late update) else append
                if existing.iloc[-1]["timestamp"] == row.iloc[0]["timestamp"]:
                    self._buffers[sym] = pd.concat([existing.iloc[:-1], row], ignore_index=True)
                else:
                    self._buffers[sym] = pd.concat([existing, row], ignore_index=True).tail(
                        max(settings.alpaca_seed_bar_limit, 500)
                    ).reset_index(drop=True)
        self._last_bar_at = datetime.now(timezone.utc)

    # --- MarketDataProvider interface ----------------------------------
    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        symbol = symbol.upper()
        if self._seed_error:
            raise ProviderUnavailableError(f"Alpaca unavailable: {self._seed_error}")
        if self._ws_state == "auth_failed":
            raise ProviderUnavailableError(f"Alpaca unavailable: {self._ws_error}")
        with self._lock:
            df = self._buffers.get(symbol)
        if df is None or df.empty:
            raise ProviderUnavailableError(f"No Alpaca data buffered yet for {symbol}")
        return df.tail(limit).reset_index(drop=True)

    def get_latest_candle(self, symbol: str) -> pd.Series:
        return self.get_ohlcv(symbol, limit=1).iloc[-1]


class YFinanceProvider(MarketDataProvider):
    """Delayed provider backed by Yahoo Finance via the `yfinance` package.

    This is the default provider for the India (NSE/BSE) market: it needs no
    broker account, API key or KYC. In exchange it is an UNOFFICIAL wrapper
    around Yahoo's endpoints (no SLA, can break or rate-limit, licence for
    redistribution is Yahoo's, not ours) and NSE/BSE data is commonly delayed.

    Honesty notes:
    - `data_status` is always "delayed", never "live", regardless of how fresh
      a response looks. Yahoo publishes no latency guarantee.
    - There is no push/WebSocket for this source. Each poll pulls candles; a
      short TTL cache (settings.yfinance_cache_ttl_seconds) keeps the
      dashboard's polling from hammering Yahoo.
    - A symbol that cannot be qualified or that Yahoo has no data for raises
      ProviderUnavailableError. It is NEVER replaced by another symbol or by
      US/demo data.
    """

    name = "yfinance"
    feed = "yahoo"
    data_status = "delayed"
    is_live = False
    supported_markets = ("IN", "US")

    def __init__(self, symbols: Optional[list[str]] = None, market: str = "IN", exchange: Optional[str] = None) -> None:
        import threading

        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise ValueError("yfinance is not installed (pip install yfinance)") from exc

        from backend.config.market import get_market, resolve_exchange

        self.market: MarketSpec = get_market(market)
        self.exchange: str = resolve_exchange(self.market, exchange)
        self.symbols = [self._qualify(s) for s in (symbols or [])]
        self._cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
        self._cache_lock = threading.Lock()
        self._last_latency_ms: Optional[float] = None

    def _qualify(self, symbol: str) -> str:
        return qualify_symbol(symbol, self.market, self.exchange)

    def _cache_key(self, qualified: str) -> tuple:
        # market + exchange + symbol + interval + period: a change to any of
        # them must never be served another configuration's candles.
        return (self.market.code, self.exchange, qualified, settings.yfinance_interval, settings.yfinance_period)

    def _normalise(self, hist: pd.DataFrame, qualified: str) -> pd.DataFrame:
        hist = hist.reset_index()
        time_col = next((c for c in ("Datetime", "Date", "index") if c in hist.columns), None)
        required = {"Open", "High", "Low", "Close", "Volume"}
        if time_col is None or not required.issubset(hist.columns):
            raise ProviderUnavailableError(f"yfinance returned an unexpected schema for {qualified}: {list(hist.columns)}")

        ts = pd.to_datetime(hist[time_col])
        if ts.dt.tz is None:
            # Naive timestamps are exchange-local wall-clock time. Labelling them UTC
            # would shift every candle by the UTC offset (5h30m for IST).
            ts = ts.dt.tz_localize(self.market.tz, ambiguous="NaT", nonexistent="NaT")
        ts = ts.dt.tz_convert("UTC")

        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": pd.to_numeric(hist["Open"], errors="coerce"),
                "high": pd.to_numeric(hist["High"], errors="coerce"),
                "low": pd.to_numeric(hist["Low"], errors="coerce"),
                "close": pd.to_numeric(hist["Close"], errors="coerce"),
                "volume": pd.to_numeric(hist["Volume"], errors="coerce"),
            }
        )
        # Yahoo emits NaN OHLC rows for missing intervals; drop them rather than
        # forward-filling (which would fabricate candles).
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        df["volume"] = df["volume"].fillna(0.0)
        df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
        df = df.drop_duplicates(subset="timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
        if df.empty:
            raise ProviderUnavailableError(f"yfinance returned only invalid candles for {qualified}")
        return df

    def _fetch(self, symbol: str) -> pd.DataFrame:
        import time

        import yfinance as yf

        try:
            qualified = self._qualify(symbol)
        except InvalidSymbolError as exc:
            raise ProviderUnavailableError(f"invalid symbol for {self.market.name}/{self.exchange}: {exc}") from exc

        key = self._cache_key(qualified)
        ttl = settings.yfinance_cache_ttl_seconds
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
        if hit is not None and ttl > 0 and now - hit[0] < ttl:
            return hit[1]

        t0 = time.monotonic()
        try:
            hist = yf.Ticker(qualified).history(
                period=settings.yfinance_period,
                interval=settings.yfinance_interval,
                auto_adjust=False,
            )
        except Exception as exc:  # yfinance raises assorted exceptions on network/format/rate-limit errors
            raise ProviderUnavailableError(f"yfinance error for {qualified}: {exc}") from exc
        self._last_latency_ms = (time.monotonic() - t0) * 1000

        if hist is None or hist.empty:
            raise ProviderUnavailableError(f"yfinance returned no data for {qualified} (bad symbol, delisted, or no data)")

        df = self._normalise(hist, qualified)
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), df)
        return df

    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        df = self._fetch(symbol)
        return df.tail(limit).reset_index(drop=True)

    def get_latest_candle(self, symbol: str) -> pd.Series:
        df = self._fetch(symbol)
        return df.iloc[-1]


class _UnavailableProvider(MarketDataProvider):
    """Stub used when a provider was explicitly requested but cannot serve the
    selected market / cannot be constructed (no credentials, wrong market,
    unknown provider name). Never pretends to be demo data - every call raises
    ProviderUnavailableError so the UI shows DATA UNAVAILABLE."""

    data_status = "unavailable"
    is_live = False

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    def get_ohlcv(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        raise ProviderUnavailableError(f"{self.name} not configured: {self.reason}")

    def get_latest_candle(self, symbol: str) -> pd.Series:
        raise ProviderUnavailableError(f"{self.name} not configured: {self.reason}")


def get_provider() -> MarketDataProvider:
    """Factory selecting the configured provider for the configured market.

    Rules (none of them ever substitutes US data for an Indian selection):
    - A provider that does not support the selected market yields an
      `_UnavailableProvider` with an explanatory reason.
    - An unknown MARKET_DATA_PROVIDER value yields `_UnavailableProvider`;
      it is NOT silently treated as demo.
    - "demo" is only used when explicitly requested (or, as before, when
      Alpha Vantage is selected for a supported market without a key) and is
      always labelled as demo data.
    - Alpaca never falls back to demo (existing behaviour, unchanged).
    """
    provider_name = settings.market_data_provider.strip().lower()
    market = settings.market_spec

    def _unsupported(name: str) -> "_UnavailableProvider":
        reason = (
            f"{name} does not serve the {market.name} market ({market.code}). "
            f"Use MARKET_DATA_PROVIDER=yfinance for NSE/BSE data."
        )
        logger.error(reason)
        return _UnavailableProvider(name, reason)

    if provider_name == "yfinance":
        try:
            return YFinanceProvider(settings.watchlist_symbols, market.code, settings.exchange_code)
        except ValueError as exc:
            logger.error("yfinance provider misconfigured: %s", exc)
            return _UnavailableProvider("yfinance", str(exc))

    if provider_name == "alpaca":
        if market.code not in AlpacaProvider.supported_markets:
            return _unsupported("alpaca")
        try:
            return AlpacaProvider(settings.alpaca_api_key, settings.alpaca_api_secret, settings.watchlist_symbols)
        except ValueError as exc:
            # missing credentials entirely: still don't fall back to demo
            logger.error("Alpaca provider misconfigured: %s", exc)
            return _UnavailableProvider("alpaca", str(exc))

    if provider_name == "alphavantage":
        if market.code not in AlphaVantageProvider.supported_markets:
            return _unsupported("alphavantage")
        if settings.alphavantage_api_key:
            try:
                return AlphaVantageProvider(settings.alphavantage_api_key, settings.alphavantage_entitlement)
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("Falling back to demo data provider: %s", exc)
        return DemoDataProvider()

    if provider_name == "demo":
        return DemoDataProvider()

    reason = f"unknown MARKET_DATA_PROVIDER {settings.market_data_provider!r}; expected yfinance | demo | alphavantage | alpaca"
    logger.error(reason)
    return _UnavailableProvider(provider_name or "unset", reason)
