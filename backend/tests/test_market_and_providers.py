"""India-default market configuration, symbol handling, Yahoo normalisation and session logic.

Provider behaviour is tested against a recording fake `yfinance.Ticker`
(see conftest.py); nothing here needs network access or credentials.
"""
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backend.config.market import (
    INDIA,
    LEGACY_US_DEFAULT_WATCHLIST,
    US,
    InvalidSymbolError,
    qualify_symbol,
    session_status,
)
from backend.config.settings import Settings, settings
from backend.data.providers import (
    DemoDataProvider,
    ProviderUnavailableError,
    YFinanceProvider,
    _UnavailableProvider,
    get_provider,
)
from backend.features.engineering import FEATURE_COLUMNS, build_features
from backend.tests.conftest import make_yahoo_history

# ---------------------------------------------------------------- defaults
def test_clean_settings_default_to_india_nse_inr_ist():
    s = Settings(_env_file=None)          # ignores any local backend/.env
    assert s.market == "IN"
    assert s.exchange_code == "NSE"
    assert s.market_data_provider == "yfinance"
    assert s.display_currency_symbol == "\u20b9"
    assert s.market_spec.currency_code == "INR"
    assert s.market_spec.timezone == "Asia/Kolkata"
    assert s.config_warnings == []


def test_default_watchlist_is_valid_nse_symbols_and_has_no_us_tickers():
    syms = Settings(_env_file=None).watchlist_symbols
    assert len(syms) >= 5
    assert all(s.endswith(".NS") for s in syms)
    assert not {s.split(".")[0] for s in syms} & set(LEGACY_US_DEFAULT_WATCHLIST)


def test_bse_selection_uses_bo_suffix():
    s = Settings(_env_file=None, exchange="bse", watchlist="RELIANCE,TCS.BO")
    assert s.exchange_code == "BSE"
    assert s.watchlist_symbols == ["RELIANCE.BO", "TCS.BO"]


def test_stale_us_watchlist_is_flagged_never_swapped():
    s = Settings(_env_file=None, watchlist="AAPL,TCS")
    assert s.watchlist_symbols == ["AAPL.NS", "TCS.NS"]          # interpreted as NSE, not as Nasdaq
    assert any("US tickers" in w for w in s.config_warnings)


def test_stale_dollar_currency_is_ignored_with_warning():
    s = Settings(_env_file=None, currency_symbol="$")
    assert s.display_currency_symbol == "\u20b9"
    assert any("CURRENCY_SYMBOL" in w for w in s.config_warnings)


def test_us_market_still_supported_and_isolated():
    s = Settings(_env_file=None, market="US", watchlist_us="AAPL,MSFT")
    assert s.watchlist_symbols == ["AAPL", "MSFT"]
    assert s.display_currency_symbol == "$"
    assert Settings(_env_file=None).watchlist_symbols != s.watchlist_symbols   # default unaffected


# ---------------------------------------------------------------- symbols
@pytest.mark.parametrize(
    "raw, exchange, expected",
    [
        ("reliance", "NSE", "RELIANCE.NS"),
        ("RELIANCE.NS", "NSE", "RELIANCE.NS"),
        ("RELIANCE", "BSE", "RELIANCE.BO"),
        ("TCS.BO", "NSE", "TCS.BO"),                  # explicit suffix wins
        ("M&M", "NSE", "M&M.NS"),
        ("BAJAJ-AUTO", "NSE", "BAJAJ-AUTO.NS"),
    ],
)
def test_qualify_symbol_india(raw, exchange, expected):
    assert qualify_symbol(raw, INDIA, exchange) == expected


@pytest.mark.parametrize("raw", ["", "BRK.B", "VOD.L", "RELIANCE.NSE", "AB CD", "A" * 30])
def test_qualify_symbol_rejects_foreign_or_malformed(raw):
    with pytest.raises(InvalidSymbolError):
        qualify_symbol(raw, INDIA, "NSE")


def test_us_symbols_not_suffixed():
    assert qualify_symbol("aapl", US) == "AAPL"
    with pytest.raises(InvalidSymbolError):
        qualify_symbol("RELIANCE.NS", US)


def test_us_share_class_uses_yahoo_dash_form_and_exchange_suffixes_are_rejected():
    assert qualify_symbol("brk.b", US) == "BRK-B"
    assert qualify_symbol("BRK-B", US) == "BRK-B"
    for bad in ("RELIANCE.NS", "AAPL.NS", "TCS.BO", "", "TOOLONGNAME", "AB CD", "1234"):
        with pytest.raises(InvalidSymbolError):
            qualify_symbol(bad, US)


# ---------------------------------------------------------------- provider selection
def test_default_provider_is_yfinance_for_india(pinned_india_settings):
    p = get_provider()
    assert isinstance(p, YFinanceProvider)
    assert (p.market.code, p.exchange, p.data_status, p.is_live) == ("IN", "NSE", "delayed", False)


@pytest.mark.parametrize("name", ["alpaca", "alphavantage"])
def test_us_only_providers_are_refused_for_india_and_open_no_subscription(monkeypatch, pinned_india_settings, name):
    monkeypatch.setattr(settings, "market_data_provider", name)
    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(settings, "alphavantage_api_key", "k")
    p = get_provider()
    assert isinstance(p, _UnavailableProvider)               # no Alpaca socket / AV request can be created
    assert p.data_status == "unavailable"
    with pytest.raises(ProviderUnavailableError, match="does not serve"):
        p.get_ohlcv("RELIANCE.NS")


def test_unknown_provider_name_is_not_silently_demo(monkeypatch, pinned_india_settings):
    monkeypatch.setattr(settings, "market_data_provider", "yfinnance")      # typo
    p = get_provider()
    assert isinstance(p, _UnavailableProvider) and not isinstance(p, DemoDataProvider)


def test_demo_only_when_explicit_and_labelled(monkeypatch, pinned_india_settings):
    monkeypatch.setattr(settings, "market_data_provider", "demo")
    p = get_provider()
    assert isinstance(p, DemoDataProvider) and p.data_status == "demo" and p.is_live is False


# ---------------------------------------------------------------- Yahoo normalisation
def test_yahoo_ist_index_is_converted_to_utc_and_columns_normalised(fake_yahoo):
    p = YFinanceProvider(market="IN", exchange="NSE")
    df = p.get_ohlcv("RELIANCE.NS", limit=100)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert df["timestamp"].is_monotonic_increasing
    assert all(df[c].dtype == "float64" for c in ["open", "high", "low", "close", "volume"])
    first_local = df["timestamp"].iloc[0].tz_convert("Asia/Kolkata")
    assert (first_local.hour, first_local.minute) >= (9, 15)
    assert len(df) == 100


def test_naive_yahoo_timestamps_are_treated_as_ist_not_utc(fake_yahoo):
    fake_yahoo.data["TCS.NS"] = make_yahoo_history(tz=None)               # naive wall-clock IST
    df = YFinanceProvider(market="IN", exchange="NSE").get_ohlcv("TCS.NS", limit=50)
    local = df["timestamp"].dt.tz_convert("Asia/Kolkata")
    assert ((local.dt.hour * 60 + local.dt.minute) >= 9 * 60 + 15).all()


def test_missing_and_invalid_candles_are_dropped_not_filled(fake_yahoo):
    h = make_yahoo_history(n=120)
    h.iloc[10, h.columns.get_loc("Close")] = float("nan")
    h.iloc[20, h.columns.get_loc("Open")] = 0.0
    h = pd.concat([h, h.iloc[[-1]]])                                       # duplicate timestamp
    fake_yahoo.data["ITC.NS"] = h
    df = YFinanceProvider(market="IN", exchange="NSE").get_ohlcv("ITC.NS", limit=500)
    assert len(df) == 118
    assert df["timestamp"].is_unique and not df.isna().any().any()


def test_empty_response_unknown_symbol_error_and_bad_schema_all_raise(fake_yahoo):
    p = YFinanceProvider(market="IN", exchange="NSE")
    with pytest.raises(ProviderUnavailableError, match="no data"):
        p.get_ohlcv("NOSUCHCO.NS")
    fake_yahoo.data["LT.NS"] = RuntimeError("429 Too Many Requests")
    with pytest.raises(ProviderUnavailableError, match="429"):
        p.get_ohlcv("LT.NS")
    fake_yahoo.data["SBIN.NS"] = pd.DataFrame({"Foo": [1]}, index=pd.DatetimeIndex(["2026-10-28"], name="Datetime"))
    with pytest.raises(ProviderUnavailableError, match="schema"):
        p.get_ohlcv("SBIN.NS")


def test_no_us_ticker_replaces_an_unavailable_indian_symbol(fake_yahoo):
    fake_yahoo.data.pop("INFY.NS")
    p = YFinanceProvider(market="IN", exchange="NSE")
    with pytest.raises(ProviderUnavailableError):
        p.get_ohlcv("INFY.NS")
    assert fake_yahoo.calls == ["INFY.NS"]                                 # no fallback request of any kind
    with pytest.raises(ProviderUnavailableError, match="invalid symbol"):
        p.get_ohlcv("BRK.B")
    assert fake_yahoo.calls == ["INFY.NS"]                                 # rejected before reaching Yahoo


def test_cache_key_separates_exchange_and_ttl_is_honoured(fake_yahoo, monkeypatch):
    monkeypatch.setattr(settings, "yfinance_cache_ttl_seconds", 300)
    fake_yahoo.data["RELIANCE.BO"] = make_yahoo_history(base=1111.0, seed=99)
    nse = YFinanceProvider(market="IN", exchange="NSE")
    bse = YFinanceProvider(market="IN", exchange="BSE")
    a1 = nse.get_ohlcv("RELIANCE", limit=5)
    a2 = nse.get_ohlcv("RELIANCE", limit=5)
    b = bse.get_ohlcv("RELIANCE", limit=5)
    assert fake_yahoo.calls == ["RELIANCE.NS", "RELIANCE.BO"]              # 2nd NSE read came from cache
    assert a1.equals(a2) and not a1["close"].equals(b["close"])
    assert nse._cache_key("RELIANCE.NS") != bse._cache_key("RELIANCE.BO")


def test_us_market_provider_does_not_suffix(fake_yahoo):
    fake_yahoo.data["AAPL"] = make_yahoo_history(base=190.0, tz="America/New_York")
    df = YFinanceProvider(market="US").get_ohlcv("aapl", limit=10)
    assert fake_yahoo.calls == ["AAPL"] and len(df) == 10


# ---------------------------------------------------------------- engine on Indian data
def test_breakout_features_and_inference_accept_indian_candles(fake_yahoo):
    from backend.inference.pipeline import run_inference_cycle

    p = YFinanceProvider(market="IN", exchange="NSE")
    raw = p.get_ohlcv("HDFCBANK.NS", limit=300)
    feats = build_features(raw)
    assert not feats[FEATURE_COLUMNS].iloc[-1].isna().any()
    results, _ = run_inference_cycle(["HDFCBANK.NS"], p)
    r = results[0]
    assert r.error in (None, "model_unavailable")
    assert r.current_price == pytest.approx(float(fake_yahoo.data["HDFCBANK.NS"]["Close"].iloc[-1]))   # the INR price, untouched
    assert r.breakout_probability is None or 0.0 <= r.breakout_probability <= 1.0


# ---------------------------------------------------------------- sessions / time zones
@pytest.mark.parametrize(
    "utc, state, reason",
    [
        ("2026-10-29T03:30:00", "closed", "before_open"),   # Thu 09:00 IST
        ("2026-10-29T03:45:00", "open", "in_session"),      # Thu 09:15 IST (inclusive)
        ("2026-10-29T09:59:00", "open", "in_session"),      # Thu 15:29 IST
        ("2026-10-29T10:00:00", "closed", "after_close"),   # Thu 15:30 IST (exclusive)
        ("2026-10-31T06:00:00", "closed", "weekend"),       # Sat
        ("2026-11-01T06:00:00", "closed", "weekend"),       # Sun
    ],
)
def test_session_status_in_ist(utc, state, reason):
    st = session_status(INDIA, datetime.fromisoformat(utc).replace(tzinfo=timezone.utc))
    assert (st["state"], st["reason"]) == (state, reason)
    assert st["timezone"] == "Asia/Kolkata" and st["session_open"] == "09:15" and st["session_close"] == "15:30"


def test_configured_holiday_closes_market_and_next_open_skips_weekend():
    thu = datetime(2026, 10, 29, 5, 0, tzinfo=timezone.utc)            # 10:30 IST, would be open
    assert session_status(INDIA, thu)["state"] == "open"
    st = session_status(INDIA, thu, holidays={date(2026, 10, 29)})
    assert (st["state"], st["reason"], st["holiday_calendar_configured"]) == ("closed", "holiday", True)
    fri_after_close = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    assert session_status(INDIA, fri_after_close)["next_open"].startswith("2026-11-02T09:15:00+05:30")


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        session_status(INDIA, datetime(2026, 10, 29, 10, 0))


def test_sharpe_annualisation_uses_nse_session_not_us(monkeypatch, pinned_india_settings):
    from backend.backtesting import backtest

    monkeypatch.setattr(settings, "demo_candle_interval_minutes", 5)
    import numpy as np

    r = np.array([0.01, -0.005, 0.02, 0.0, 0.004])
    nse = backtest._sharpe(r)
    assert nse == pytest.approx(backtest._sharpe(r, periods_per_year=248 * 75))
    assert nse != pytest.approx(backtest._sharpe(r, periods_per_year=252 * 78))


# ---------------------------------------------------------------- persisted frontend state
def test_frontend_hardcodes_no_tickers_and_only_prefs_module_touches_browser_storage():
    """Default tickers live in backend/config/market.py only (the UI reads them from the API).
    Browser storage is limited to one convenience (the last selected market) in lib/prefs.js."""
    src = Path(__file__).resolve().parents[2] / "frontend" / "src"
    files = [
        p for p in src.rglob("*")
        if p.suffix in {".js", ".jsx"} and ".test." not in p.name and ".spec." not in p.name
    ]
    text = "\n".join(p.read_text() for p in files if p.name != "prefs.js")
    tickers = (*LEGACY_US_DEFAULT_WATCHLIST, "RELIANCE", "HDFCBANK", "TATAMOTORS", "NFLX")
    for needle in ("localStorage", "sessionStorage", *tickers):
        assert needle not in text, f"{needle} found in frontend source"
    assert 'currencySymbol = "$"' not in text
