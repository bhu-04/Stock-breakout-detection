"""Shared, hermetic fixtures.

No test here touches the network: Yahoo Finance is replaced by a recording
fake `yfinance.Ticker`. Settings are pinned explicitly so a developer's local
backend/.env (which may still contain the old US watchlist) cannot change the
outcome of a test run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.config.market import DEFAULT_INDIA_WATCHLIST, DEFAULT_US_WATCHLIST
from backend.config.settings import settings

IST = "Asia/Kolkata"
NY = "America/New_York"
US_SESSION = ("09:30", "15:55")        # last 5-minute candle of the 09:30-16:00 ET session


def make_yahoo_history(
    n: int = 300, base: float = 2800.0, tz: str | None = IST, seed: int = 7, session: tuple = ("09:15", "15:25")
) -> pd.DataFrame:
    """A DataFrame shaped like `yfinance.Ticker.history(interval="5m")`:
    tz-aware DatetimeIndex named "Datetime". Defaults model an NSE stock (IST session, INR on the
    0.05 tick); pass tz=NY, session=US_SESSION for a US stock."""
    rng = np.random.default_rng(seed)
    # 5-minute candles inside the regular session, ending on a past weekday
    per_day = len(pd.date_range("2026-01-05 " + session[0], "2026-01-05 " + session[1], freq="5min"))
    days = pd.bdate_range(end="2026-10-28", periods=n // per_day + 2)
    idx = []
    for d in days:
        idx.extend(pd.date_range(f"{d.date()} {session[0]}", f"{d.date()} {session[1]}", freq="5min"))
    idx = pd.DatetimeIndex(idx[-n:], name="Datetime")
    idx = idx.tz_localize(tz) if tz else idx

    close = base * np.exp(np.cumsum(rng.normal(0, 0.0015, len(idx))))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0.0002, 0.002, len(idx)))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.0002, 0.002, len(idx)))
    tick = lambda x: np.round(x / 0.05) * 0.05  # noqa: E731
    return pd.DataFrame(
        {
            "Open": tick(open_),
            "High": tick(high),
            "Low": tick(low),
            "Close": tick(close),
            "Volume": rng.integers(20_000, 400_000, len(idx)).astype(float),
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=idx,
    )


class FakeYahoo:
    """Replacement for `yfinance.Ticker`. Records every symbol requested.

    `data` maps provider symbol -> DataFrame (or an Exception to raise).
    Any symbol not in `data` returns an empty frame, like Yahoo does for an
    unknown ticker.
    """

    def __init__(self):
        self.data: dict = {}
        self.calls: list[str] = []

    def install(self, monkeypatch):
        import yfinance

        outer = self

        class _Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
                outer.calls.append(symbol)

            def history(self, **kwargs):
                item = outer.data.get(self.symbol)
                if isinstance(item, Exception):
                    raise item
                return item.copy() if item is not None else pd.DataFrame()

        monkeypatch.setattr(yfinance, "Ticker", _Ticker)
        return self


def make_us_history(base: float = 190.0, seed: int = 11, n: int = 300) -> pd.DataFrame:
    return make_yahoo_history(n=n, base=base, tz=NY, seed=seed, session=US_SESSION)


@pytest.fixture
def pinned_india_settings(monkeypatch, tmp_path):
    """Pin settings to the intended defaults regardless of any local .env, and point the
    watchlist store at a throw-away file (so no test ever touches real user data)."""
    for k, v in {
        "market": "IN",
        "exchange": "",
        "market_data_provider": "yfinance",
        "watchlist": ",".join(DEFAULT_INDIA_WATCHLIST),
        "watchlist_us": ",".join(DEFAULT_US_WATCHLIST),
        "currency_symbol": "",
        "market_holidays": "",
        "market_holidays_in": "",
        "market_holidays_us": "",
        "yfinance_cache_ttl_seconds": 0,
        "yfinance_interval": "5m",
        "yfinance_period": "5d",
        "watchlist_store_path": str(tmp_path / "watchlists.json"),
        "watchlist_readonly": False,
        "max_watchlist_size": 50,
        "min_history_candles": 60,
        "max_fetch_concurrency": 4,
    }.items():
        monkeypatch.setattr(settings, k, v)
    return settings


pinned_settings = pinned_india_settings      # clearer alias for multi-market tests


@pytest.fixture
def fake_yahoo(monkeypatch, pinned_india_settings):
    """Fake Yahoo that knows every default India symbol (INR scale) and every default US symbol (USD scale)."""
    fy = FakeYahoo().install(monkeypatch)
    for i, sym in enumerate(settings.default_watchlist("IN")):
        fy.data[sym] = make_yahoo_history(base=500.0 + 400 * i, seed=i)
    for i, sym in enumerate(settings.default_watchlist("US")):
        fy.data[sym] = make_us_history(base=120.0 + 35 * i, seed=100 + i)
    return fy


@pytest.fixture
def api_client(monkeypatch, fake_yahoo):
    """FastAPI client whose providers are the REAL YFinanceProvider (one per market, created by
    the app itself) talking to the fake Yahoo."""
    from fastapi.testclient import TestClient

    import backend.api.main as main

    monkeypatch.setattr(main, "_providers", {})
    monkeypatch.setattr(main, "_update_counts", {code: 0 for code in main.MARKETS})
    return TestClient(main.app)
