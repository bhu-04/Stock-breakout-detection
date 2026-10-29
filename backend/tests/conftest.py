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

from backend.config.market import DEFAULT_INDIA_WATCHLIST
from backend.config.settings import settings

IST = "Asia/Kolkata"


def make_yahoo_history(n: int = 300, base: float = 2800.0, tz: str | None = IST, seed: int = 7) -> pd.DataFrame:
    """A DataFrame shaped like `yfinance.Ticker.history(interval="5m")` for an NSE stock:
    tz-aware IST DatetimeIndex named "Datetime", prices in INR on the 0.05 tick."""
    rng = np.random.default_rng(seed)
    # 5-minute candles inside the NSE session (09:15-15:30 IST), ending on a past weekday
    days = pd.bdate_range(end="2026-10-28", periods=n // 75 + 2)
    idx = []
    for d in days:
        idx.extend(pd.date_range(f"{d.date()} 09:15", f"{d.date()} 15:25", freq="5min"))
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


@pytest.fixture
def pinned_india_settings(monkeypatch):
    """Pin settings to the intended defaults regardless of any local .env."""
    for k, v in {
        "market": "IN",
        "exchange": "",
        "market_data_provider": "yfinance",
        "watchlist": ",".join(DEFAULT_INDIA_WATCHLIST),
        "currency_symbol": "",
        "market_holidays": "",
        "yfinance_cache_ttl_seconds": 0,
        "yfinance_interval": "5m",
        "yfinance_period": "5d",
    }.items():
        monkeypatch.setattr(settings, k, v)
    return settings


@pytest.fixture
def fake_yahoo(monkeypatch, pinned_india_settings):
    fy = FakeYahoo().install(monkeypatch)
    for i, sym in enumerate(settings.watchlist_symbols):
        fy.data[sym] = make_yahoo_history(base=500.0 + 400 * i, seed=i)
    return fy


@pytest.fixture
def api_client(monkeypatch, fake_yahoo):
    """FastAPI client whose provider is the REAL YFinanceProvider talking to the fake Yahoo."""
    from fastapi.testclient import TestClient

    import backend.api.main as main
    from backend.data.providers import YFinanceProvider

    monkeypatch.setattr(main, "_provider", YFinanceProvider(settings.watchlist_symbols, "IN", "NSE"))
    return TestClient(main.app)
