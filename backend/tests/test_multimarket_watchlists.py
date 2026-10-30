"""Multi-market (India + US) dashboard backend: market selection, independent persisted
watchlists, provider routing, failure handling.

Hermetic: Yahoo Finance is replaced by the recording FakeYahoo from conftest.py, and every
test gets its own watchlist file. Nothing here needs network access.
"""
import pandas as pd
import pytest

from backend.config.market import DEFAULT_INDIA_WATCHLIST, DEFAULT_US_WATCHLIST
from backend.config.settings import settings
from backend.data import watchlist_store
from backend.tests.conftest import make_us_history, make_yahoo_history

IN_DEFAULTS = [f"{s}.NS" for s in DEFAULT_INDIA_WATCHLIST]
US_DEFAULTS = list(DEFAULT_US_WATCHLIST)


def symbols_of(client, market):
    return [i["symbol"] for i in client.get(f"/api/watchlist?market={market}").json()["symbols"]]


def add(client, market, symbol):
    return client.post("/api/watchlist", json={"market": market, "symbol": symbol})


@pytest.fixture
def yahoo_knows_extras(fake_yahoo):
    """Extra, valid instruments on each side so they can be added."""
    for i, s in enumerate(["TATAMOTORS.NS", "MARUTI.NS", "BAJFINANCE.NS", "WIPRO.NS", "AXISBANK.NS", "NTPC.NS", "ONGC.NS"]):
        fake_yahoo.data[s] = make_yahoo_history(base=400.0 + 90 * i, seed=300 + i)
    for i, s in enumerate(["NFLX", "ORCL", "COST", "INTC", "BRK-B", "PEP", "KO"]):
        fake_yahoo.data[s] = make_us_history(base=60.0 + 70 * i, seed=400 + i)
    return fake_yahoo


# ===================================================================== markets & defaults
def test_markets_endpoint_lists_india_and_us_with_labels_currency_and_timezone(api_client):
    body = api_client.get("/api/markets").json()
    assert body["default_market"] == "IN"                                   # first-time user sees India
    by_code = {m["market"]: m for m in body["markets"]}
    assert set(by_code) == {"IN", "US"}
    assert by_code["IN"]["label"] == "NSE · India" and by_code["IN"]["option_label"] == "India — NSE"
    assert by_code["US"]["label"] == "US Equities · United States"
    assert by_code["US"]["option_label"] == "United States — US equities"
    assert (by_code["IN"]["currency_symbol"], by_code["IN"]["timezone"]) == ("₹", "Asia/Kolkata")
    assert (by_code["US"]["currency_symbol"], by_code["US"]["timezone"]) == ("$", "America/New_York")
    assert by_code["IN"]["watchlist_size"] == 10 and by_code["US"]["watchlist_size"] == 10
    assert by_code["US"]["provider_supports_market"] is True and by_code["US"]["example_symbols"]


def test_each_market_has_its_own_default_watchlist(api_client):
    assert symbols_of(api_client, "IN") == IN_DEFAULTS
    assert symbols_of(api_client, "US") == US_DEFAULTS
    assert not set(symbols_of(api_client, "IN")) & set(symbols_of(api_client, "US"))
    assert all(i["is_default"] for i in api_client.get("/api/watchlist?market=US").json()["symbols"])


def test_market_defaults_to_india_when_omitted(api_client):
    body = api_client.get("/api/opportunities").json()
    assert body["market"] == "IN" and body["market_info"]["currency_symbol"] == "₹"
    assert sorted(o["symbol"] for o in body["opportunities"]) == sorted(IN_DEFAULTS)
    assert api_client.get("/api/watchlist").json()["market"] == "IN"


def test_us_selection_loads_us_watchlist_with_dollars_and_new_york_time(api_client, fake_yahoo):
    body = api_client.get("/api/opportunities?market=US").json()
    info = body["market_info"]
    assert body["market"] == "US" and (info["currency_code"], info["currency_symbol"], info["timezone"]) == ("USD", "$", "America/New_York")
    assert info["exchange"] == "US" and info["session"]["session_open"] == "09:30" and info["session"]["timezone"] == "America/New_York"
    assert sorted(o["symbol"] for o in body["opportunities"]) == sorted(US_DEFAULTS)
    assert not any(s.endswith(".NS") for s in fake_yahoo.calls)                 # not one Indian request
    assert set(fake_yahoo.calls) == set(US_DEFAULTS)
    for o in body["opportunities"]:                                             # each symbol carries ITS OWN price
        assert o["current_price"] == pytest.approx(float(fake_yahoo.data[o["symbol"]]["Close"].iloc[-1]), abs=0.01)


def test_switching_markets_never_mixes_symbols_or_data(api_client, fake_yahoo):
    seen = []
    for market in ["IN", "US", "IN", "US", "US", "IN"]:
        body = api_client.get(f"/api/opportunities?market={market}").json()
        syms = {o["symbol"] for o in body["opportunities"]}
        expected = set(IN_DEFAULTS if market == "IN" else US_DEFAULTS)
        assert body["market"] == market and syms == expected
        seen.append(market)
    in_calls = [c for c in fake_yahoo.calls if c.endswith(".NS")]
    us_calls = [c for c in fake_yahoo.calls if not c.endswith(".NS")]
    assert set(in_calls) == set(IN_DEFAULTS) and set(us_calls) == set(US_DEFAULTS)


def test_provider_instances_and_cache_keys_are_per_market(api_client):
    import backend.api.main as main

    api_client.get("/api/opportunities?market=IN")
    api_client.get("/api/opportunities?market=US")
    assert set(main._providers) == {"IN", "US"} and main._providers["IN"] is not main._providers["US"]
    assert main._providers["IN"].market.code == "IN" and main._providers["US"].market.code == "US"
    assert main._providers["IN"]._cache_key("X") != main._providers["US"]._cache_key("X")


def test_update_counts_are_per_market(api_client):
    api_client.get("/api/opportunities?market=IN")
    api_client.get("/api/opportunities?market=IN")
    us = api_client.get("/api/opportunities?market=US").json()
    assert us["summary"]["live_update_count"] == 1
    assert api_client.get("/api/health?market=IN").json()["update_count"] == 2


def test_health_is_market_specific(api_client):
    us = api_client.get("/api/health?market=US").json()
    assert (us["market"], us["currency_symbol"], us["watchlist_size"], us["data_status"]) == ("US", "$", 10, "delayed")
    assert us["is_live_data"] is False                                          # never claims a live feed
    assert api_client.get("/api/health").json()["market_info"]["market"] == "IN"


# ===================================================================== add
def test_add_valid_indian_symbol_updates_only_the_indian_watchlist(api_client, yahoo_knows_extras):
    resp = add(api_client, "IN", "tatamotors")                                  # bare, lower-case
    assert resp.status_code == 200
    body = resp.json()
    assert body["added"] == "TATAMOTORS.NS" and body["market"] == "IN" and body["customized"] is True
    assert symbols_of(api_client, "IN") == IN_DEFAULTS + ["TATAMOTORS.NS"]
    assert symbols_of(api_client, "US") == US_DEFAULTS
    added = [i for i in body["symbols"] if i["symbol"] == "TATAMOTORS.NS"][0]
    assert added["is_default"] is False


def test_add_valid_us_symbol_updates_only_the_us_watchlist_without_suffix(api_client, yahoo_knows_extras):
    resp = add(api_client, "US", "nflx")
    assert resp.status_code == 200 and resp.json()["added"] == "NFLX"
    assert symbols_of(api_client, "US") == US_DEFAULTS + ["NFLX"]
    assert symbols_of(api_client, "IN") == IN_DEFAULTS
    assert "NFLX.NS" not in yahoo_knows_extras.calls                            # never suffixed
    assert add(api_client, "US", "BRK.B").json()["added"] == "BRK-B"            # share class -> Yahoo's dash form


def test_added_symbol_appears_in_the_dashboard_data_immediately_with_its_own_values(api_client, yahoo_knows_extras):
    add(api_client, "IN", "WIPRO")
    rows = {o["symbol"]: o for o in api_client.get("/api/opportunities?market=IN").json()["opportunities"]}
    assert "WIPRO.NS" in rows and rows["WIPRO.NS"]["is_default"] is False and rows["HDFCBANK.NS"]["is_default"] is True
    assert rows["WIPRO.NS"]["current_price"] == pytest.approx(float(yahoo_knows_extras.data["WIPRO.NS"]["Close"].iloc[-1]), abs=0.01)


def test_duplicate_symbol_is_rejected_in_every_spelling(api_client, yahoo_knows_extras):
    for spelling in ("RELIANCE", "reliance", "RELIANCE.NS", " Reliance.ns "):
        resp = add(api_client, "IN", spelling)
        assert resp.status_code == 409 and "already in" in resp.json()["detail"], spelling
    assert add(api_client, "IN", "MARUTI").status_code == 200
    assert add(api_client, "IN", "MARUTI.NS").status_code == 409
    assert add(api_client, "US", "AAPL").status_code == 409
    assert symbols_of(api_client, "IN").count("MARUTI.NS") == 1 and len(symbols_of(api_client, "IN")) == 11


def test_same_ticker_text_may_exist_in_both_markets_independently(api_client, yahoo_knows_extras):
    yahoo_knows_extras.data["TCS"] = make_us_history(base=33.0, seed=999)       # a US-listed "TCS"
    assert add(api_client, "US", "TCS").status_code == 200                      # distinct instrument from TCS.NS
    assert "TCS" in symbols_of(api_client, "US") and "TCS.NS" in symbols_of(api_client, "IN")


@pytest.mark.parametrize("market, symbol, fragment", [
    ("IN", "AB CD", "Not a valid India symbol"),
    ("IN", "BRK.B", "Not a valid India symbol"),
    ("IN", "VOD.L", "Not a valid India symbol"),
    ("IN", "", "Not a valid India symbol"),
    ("US", "RELIANCE.NS", "Not a valid United States symbol"),
    ("US", "TCS.BO", "Not a valid United States symbol"),
    ("US", "TOOLONGTICKER", "Not a valid United States symbol"),
])
def test_malformed_or_wrong_market_symbols_get_a_helpful_422_and_no_provider_call(api_client, fake_yahoo, market, symbol, fragment):
    before = list(fake_yahoo.calls)
    resp = add(api_client, market, symbol)
    assert resp.status_code == 422 and fragment in resp.json()["detail"]
    assert fake_yahoo.calls == before                                           # rejected before reaching Yahoo
    assert symbols_of(api_client, market) == (IN_DEFAULTS if market == "IN" else US_DEFAULTS)


def test_unknown_symbol_is_a_validation_failure_not_added(api_client, fake_yahoo):
    resp = add(api_client, "US", "ZZZZ")                                       # Yahoo returns an empty frame
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "No market data found for ZZZZ" in detail and "switch markets" in detail
    assert "ZZZZ" not in symbols_of(api_client, "US")


def test_us_ticker_typed_into_india_is_not_silently_moved_to_the_us_market(api_client, fake_yahoo):
    resp = add(api_client, "IN", "NVDA")                                       # NVDA is a default *US* symbol
    assert resp.status_code in (409, 422) or resp.status_code == 422
    assert "NVDA.NS" in fake_yahoo.calls and "NVDA" not in [c for c in fake_yahoo.calls]  # asked Yahoo for the NSE instrument only
    assert resp.status_code == 422 and "NVDA.NS" in resp.json()["detail"]
    assert symbols_of(api_client, "IN") == IN_DEFAULTS and symbols_of(api_client, "US") == US_DEFAULTS


@pytest.mark.parametrize("failure", [RuntimeError("429 Too Many Requests"), TimeoutError("read timed out"), ConnectionError("network down")])
def test_provider_outage_is_reported_as_503_distinct_from_invalid_and_nothing_is_added(api_client, yahoo_knows_extras, failure):
    yahoo_knows_extras.data["NFLX"] = failure
    resp = add(api_client, "US", "NFLX")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "Could not verify NFLX" in detail and "Nothing was added" in detail and "No market data found" not in detail
    assert "NFLX" not in symbols_of(api_client, "US")                           # not fabricated as valid


def test_yfinance_rate_limit_exception_class_is_transient_and_missing_ticker_is_not(api_client, yahoo_knows_extras):
    from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

    yahoo_knows_extras.data["NFLX"] = YFRateLimitError()
    assert add(api_client, "US", "NFLX").status_code == 503
    yahoo_knows_extras.data["NFLX"] = YFPricesMissingError("NFLX", "")
    assert add(api_client, "US", "NFLX").status_code == 422


def test_symbol_with_too_little_history_is_rejected(api_client, yahoo_knows_extras):
    yahoo_knows_extras.data["NFLX"] = make_us_history(n=20)
    resp = add(api_client, "US", "NFLX")
    assert resp.status_code == 422 and "candles" in resp.json()["detail"]
    assert "NFLX" not in symbols_of(api_client, "US")


def test_write_endpoints_require_an_explicit_known_market(api_client):
    assert api_client.post("/api/watchlist", json={"symbol": "AAPL"}).status_code == 422
    assert add(api_client, "XX", "AAPL").status_code == 400
    assert api_client.delete("/api/watchlist/AAPL").status_code == 422
    assert api_client.post("/api/watchlist/reset", json={"market": "XX"}).status_code == 400


def test_watchlist_size_limit(api_client, yahoo_knows_extras, monkeypatch):
    monkeypatch.setattr(settings, "max_watchlist_size", 11)
    assert add(api_client, "IN", "WIPRO").status_code == 200
    resp = add(api_client, "IN", "NTPC")
    assert resp.status_code == 422 and "limited to 11" in resp.json()["detail"]


def test_company_name_is_best_effort_and_never_blocks_adding(api_client, yahoo_knows_extras, monkeypatch):
    resp = add(api_client, "US", "NFLX")                                       # fake Ticker has no get_info -> no name
    assert resp.status_code == 200 and resp.json()["company_name"] is None
    import yfinance

    monkeypatch.setattr(yfinance.Ticker, "get_info", lambda self: {"longName": "Oracle Corporation"}, raising=False)
    assert add(api_client, "US", "ORCL").json()["company_name"] == "Oracle Corporation"


# ===================================================================== remove
def test_remove_affects_only_the_selected_market(api_client, yahoo_knows_extras):
    add(api_client, "IN", "WIPRO")
    add(api_client, "US", "NFLX")
    resp = api_client.delete("/api/watchlist/WIPRO?market=IN")
    assert resp.status_code == 200 and resp.json()["removed"] == "WIPRO.NS"
    assert symbols_of(api_client, "IN") == IN_DEFAULTS
    assert symbols_of(api_client, "US") == US_DEFAULTS + ["NFLX"]
    assert api_client.delete("/api/watchlist/NFLX?market=IN").status_code == 404   # an India request cannot remove a US symbol
    assert symbols_of(api_client, "US") == US_DEFAULTS + ["NFLX"]
    assert api_client.delete("/api/watchlist/WIPRO?market=IN").status_code == 404  # already gone


def test_default_stocks_can_be_removed_and_are_reported_as_removed_defaults(api_client):
    resp = api_client.delete("/api/watchlist/tcs?market=IN")
    body = resp.json()
    assert resp.status_code == 200 and "TCS.NS" not in symbols_of(api_client, "IN")
    assert body["removed_defaults"] == ["TCS.NS"] and body["customized"] is True and "TCS.NS" in body["defaults"]
    rows = api_client.get("/api/opportunities?market=IN").json()
    assert rows["summary"]["stocks_monitored"] == 9 and all(o["symbol"] != "TCS.NS" for o in rows["opportunities"])


def test_removed_symbol_is_no_longer_served_as_stock_detail(api_client):
    assert api_client.get("/api/stock/TCS.NS?market=IN&limit=60").status_code == 200
    api_client.delete("/api/watchlist/TCS.NS?market=IN")
    assert api_client.get("/api/stock/TCS.NS?market=IN&limit=60").status_code == 404


# ===================================================================== reset
def test_restoring_india_defaults_does_not_touch_the_us_watchlist(api_client, yahoo_knows_extras):
    add(api_client, "IN", "WIPRO"); api_client.delete("/api/watchlist/TCS.NS?market=IN")
    add(api_client, "US", "NFLX"); api_client.delete("/api/watchlist/AAPL?market=US")
    us_before = symbols_of(api_client, "US")
    resp = api_client.post("/api/watchlist/reset", json={"market": "IN"})
    assert resp.status_code == 200 and resp.json()["customized"] is False
    assert symbols_of(api_client, "IN") == IN_DEFAULTS
    assert symbols_of(api_client, "US") == us_before


def test_restoring_us_defaults_does_not_touch_the_indian_watchlist(api_client, yahoo_knows_extras):
    add(api_client, "IN", "WIPRO"); api_client.delete("/api/watchlist/TCS.NS?market=IN")
    add(api_client, "US", "NFLX"); api_client.delete("/api/watchlist/AAPL?market=US")
    in_before = symbols_of(api_client, "IN")
    api_client.post("/api/watchlist/reset", json={"market": "US"})
    assert symbols_of(api_client, "US") == US_DEFAULTS
    assert symbols_of(api_client, "IN") == in_before


def test_re_adding_a_removed_default_restores_it_as_a_default(api_client):
    api_client.delete("/api/watchlist/AAPL?market=US")
    body = add(api_client, "US", "AAPL").json()
    assert body["customized"] is False and [i["is_default"] for i in body["symbols"] if i["symbol"] == "AAPL"] == [True]


# ===================================================================== persistence
def test_watchlists_survive_an_application_restart(api_client, yahoo_knows_extras, monkeypatch, pinned_india_settings):
    import backend.api.main as main

    add(api_client, "IN", "WIPRO"); api_client.delete("/api/watchlist/TCS.NS?market=IN")
    add(api_client, "US", "NFLX")
    expected_in, expected_us = symbols_of(api_client, "IN"), symbols_of(api_client, "US")

    watchlist_store._STORES.clear()                                            # "restart": drop every in-memory object
    monkeypatch.setattr(main, "_providers", {})
    assert symbols_of(api_client, "IN") == expected_in and symbols_of(api_client, "US") == expected_us
    rows = api_client.get("/api/opportunities?market=IN").json()["opportunities"]
    assert sorted(o["symbol"] for o in rows) == sorted(expected_in)


def test_store_file_keeps_only_user_changes_never_a_copy_of_the_defaults(api_client, yahoo_knows_extras, pinned_india_settings):
    import json
    from pathlib import Path

    assert not Path(settings.watchlist_store_path).exists()                     # first-time user: nothing written
    add(api_client, "US", "NFLX")
    data = json.loads(Path(settings.watchlist_store_path).read_text())
    assert data["markets"] == {"US": {"added": ["NFLX"], "removed": []}}
    api_client.post("/api/watchlist/reset", json={"market": "US"})
    assert json.loads(Path(settings.watchlist_store_path).read_text())["markets"] == {}


def test_corrupt_store_file_falls_back_to_defaults_and_keeps_the_original(api_client, pinned_india_settings):
    from pathlib import Path

    path = Path(settings.watchlist_store_path)
    path.write_text("{ not json")
    assert symbols_of(api_client, "IN") == IN_DEFAULTS
    assert list(path.parent.glob("watchlists.corrupt-*.json"))                  # moved aside, never silently overwritten


def test_readonly_deployment_blocks_every_write_but_still_serves_reads(api_client, yahoo_knows_extras, monkeypatch):
    monkeypatch.setattr(settings, "watchlist_readonly", True)
    assert add(api_client, "US", "NFLX").status_code == 403
    assert api_client.delete("/api/watchlist/AAPL?market=US").status_code == 403
    assert api_client.post("/api/watchlist/reset", json={"market": "US"}).status_code == 403
    assert api_client.get("/api/watchlist?market=US").json()["readonly"] is True
    assert api_client.get("/api/opportunities?market=US").status_code == 200


# ===================================================================== every selected symbol is processed
def test_sixteen_selected_symbols_all_appear_not_only_the_original_ten(api_client, yahoo_knows_extras):
    extras = ["TATAMOTORS", "MARUTI", "BAJFINANCE", "WIPRO", "AXISBANK", "NTPC"]
    for s in extras:
        assert add(api_client, "IN", s).status_code == 200
    yahoo_knows_extras.calls.clear()
    body = api_client.get("/api/opportunities?market=IN").json()
    assert body["summary"]["stocks_monitored"] == 16 and len(body["opportunities"]) == 16
    assert {o["symbol"] for o in body["opportunities"]} == set(IN_DEFAULTS) | {f"{s}.NS" for s in extras}
    assert set(yahoo_knows_extras.calls) == set(IN_DEFAULTS) | {f"{s}.NS" for s in extras}
    assert body["watchlist"]["size"] == 16 and body["symbol_errors"] == {}


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_results_are_identical_whatever_the_concurrency(api_client, yahoo_knows_extras, monkeypatch, workers):
    add(api_client, "US", "NFLX")
    monkeypatch.setattr(settings, "max_fetch_concurrency", workers)
    rows = api_client.get("/api/opportunities?market=US").json()["opportunities"]
    assert len(rows) == 11
    by_symbol = {o["symbol"]: o["current_price"] for o in rows}
    for sym, price in by_symbol.items():
        assert price == pytest.approx(float(yahoo_knows_extras.data[sym]["Close"].iloc[-1]), abs=0.01)


def test_empty_watchlist_returns_an_empty_valid_response(api_client):
    for s in list(US_DEFAULTS):
        api_client.delete(f"/api/watchlist/{s}?market=US")
    body = api_client.get("/api/opportunities?market=US").json()
    assert body["opportunities"] == [] and body["summary"]["stocks_monitored"] == 0 and body["watchlist"]["size"] == 0
    assert body["data_status"] == "delayed"                                      # nothing failed; not "unavailable"


# ===================================================================== failures never fabricate
def test_one_failing_symbol_is_reported_and_others_keep_their_own_values(api_client, fake_yahoo):
    fake_yahoo.data["MSFT"] = RuntimeError("429 Too Many Requests")
    body = api_client.get("/api/opportunities?market=US").json()
    rows = {o["symbol"]: o for o in body["opportunities"]}
    assert len(rows) == 10 and rows["MSFT"]["current_price"] is None and rows["MSFT"]["breakout_probability"] is None
    assert "429" in rows["MSFT"]["error"] and "MSFT" in body["symbol_errors"] and body["symbols_unavailable"] == ["MSFT"]
    assert body["data_status"] == "partial" and body["summary"]["failed_symbols"] == 1
    for sym, row in rows.items():
        if sym != "MSFT":
            assert row["current_price"] == pytest.approx(float(fake_yahoo.data[sym]["Close"].iloc[-1]), abs=0.01)
    assert len({r["current_price"] for r in rows.values() if r["current_price"]}) == 9   # nobody borrowed MSFT's slot


def test_total_provider_failure_for_one_market_does_not_affect_the_other(api_client, fake_yahoo):
    for s in US_DEFAULTS:
        fake_yahoo.data.pop(s)
    us = api_client.get("/api/opportunities?market=US").json()
    assert us["data_status"] == "unavailable" and all(o["current_price"] is None for o in us["opportunities"])
    india = api_client.get("/api/opportunities?market=IN").json()
    assert india["data_status"] == "delayed" and all(o["current_price"] for o in india["opportunities"])


def test_unexpected_data_problem_in_one_symbol_does_not_break_the_cycle(api_client, fake_yahoo, monkeypatch):
    import backend.inference.pipeline as pipeline

    real = pipeline.build_features

    def flaky(df):
        if float(df["close"].iloc[-1]) == pytest.approx(float(fake_yahoo.data["NVDA"]["Close"].iloc[-1])):
            raise ValueError("boom")
        return real(df)

    monkeypatch.setattr(pipeline, "build_features", flaky)
    body = api_client.get("/api/opportunities?market=US").json()
    rows = {o["symbol"]: o for o in body["opportunities"]}
    assert rows["NVDA"]["error"].startswith("processing_error") and rows["NVDA"]["current_price"] is None
    assert body["symbol_errors"].keys() == {"NVDA"}
    assert sum(1 for o in body["opportunities"] if o["current_price"]) == 9


# ===================================================================== stock detail per market
def test_stock_detail_is_resolved_inside_the_requested_market_only(api_client):
    us = api_client.get("/api/stock/aapl?market=US&limit=60").json()
    assert us["symbol"] == "AAPL" and us["market"] == "US" and us["market_info"]["currency_symbol"] == "$"
    assert len(us["candles"]) == 60
    assert api_client.get("/api/stock/AAPL?limit=60").status_code == 404          # default market is India
    assert api_client.get("/api/stock/RELIANCE.NS?market=US&limit=60").status_code == 404
    india = api_client.get("/api/stock/RELIANCE?market=IN&limit=60").json()
    assert india["symbol"] == "RELIANCE.NS" and india["market_info"]["currency_symbol"] == "₹"


def test_us_candle_timestamps_are_utc_and_map_into_the_new_york_session(api_client):
    candles = api_client.get("/api/stock/AAPL?market=US&limit=100").json()["candles"]
    for c in candles:
        ts = pd.Timestamp(c["timestamp"])
        assert ts.utcoffset() == pd.Timedelta(0)
        local = ts.tz_convert("America/New_York")
        assert (9, 30) <= (local.hour, local.minute) <= (15, 55)               # 2026-10-2x is EDT (UTC-4)


def test_breakout_engine_runs_on_us_candles_with_the_existing_pipeline(api_client):
    rows = api_client.get("/api/opportunities?market=US").json()["opportunities"]
    scored = [o for o in rows if o["breakout_probability"] is not None]
    assert scored, "model/pipeline should score US candles exactly like Indian ones"
    assert all(0.0 <= o["breakout_probability"] <= 1.0 and o["rank"] for o in scored)
    assert all(o["rsi"] is not None and o["relative_volume"] is not None for o in scored)
    assert {o["rank"] for o in scored} == set(range(1, len(scored) + 1))


def test_config_endpoint_lists_every_markets_watchlist(api_client):
    body = api_client.get("/api/config").json()
    assert body["default_market"] == "IN" and body["watchlists"]["US"] == US_DEFAULTS and body["watchlists"]["IN"] == IN_DEFAULTS


# ===================================================================== settings / provider units
def test_exchange_setting_applies_to_india_only(monkeypatch):
    from backend.config.settings import Settings

    s = Settings(_env_file=None, exchange="BSE")
    assert s.exchange_for("IN") == "BSE" and s.exchange_for("US") == "US"
    assert s.default_watchlist("IN")[0].endswith(".BO") and s.default_watchlist("US") == US_DEFAULTS


def test_holidays_are_configured_per_market():
    from backend.config.settings import Settings

    s = Settings(_env_file=None, market_holidays_in="2026-11-09", market_holidays_us="2026-12-24", market_holidays="2026-10-20")
    from datetime import date

    assert s.holidays_for("IN") == {date(2026, 11, 9), date(2026, 10, 20)}      # legacy var follows the default market
    assert s.holidays_for("US") == {date(2026, 12, 24)}


def test_yahoo_error_classification(fake_yahoo):
    from backend.data.providers import ProviderUnavailableError, SymbolNotFoundError, YFinanceProvider

    p = YFinanceProvider(market="US")
    with pytest.raises(SymbolNotFoundError):
        p.get_ohlcv("ZZZZ")                                                     # empty frame
    fake_yahoo.data["AAPL"] = RuntimeError("429 Too Many Requests")
    with pytest.raises(ProviderUnavailableError) as ei:
        p.get_ohlcv("AAPL")
    assert not isinstance(ei.value, SymbolNotFoundError)


def test_yfinance_cache_purges_entries_nobody_asked_for(fake_yahoo, monkeypatch):
    from backend.data.providers import YFinanceProvider

    monkeypatch.setattr(settings, "yfinance_cache_ttl_seconds", 30)
    p = YFinanceProvider(market="US")
    p.get_ohlcv("AAPL", 5)
    key = p._cache_key("AAPL")
    ts, df = p._cache[key]
    p._cache[key] = (ts - 10_000, df)                                           # long-stale entry (symbol since removed)
    p.get_ohlcv("MSFT", 5)
    assert key not in p._cache and p._cache_key("MSFT") in p._cache


def test_alpaca_provider_follows_the_active_watchlist_without_a_network(monkeypatch):
    """Subscription bookkeeping only (no sockets): new symbols are seeded + queued for
    subscription, removed ones are dropped + queued for unsubscription."""
    import threading

    from backend.data.providers import AlpacaProvider

    p = object.__new__(AlpacaProvider)
    p._lock = threading.Lock()
    p._buffers = {"AAPL": pd.DataFrame({"x": [1]}), "MSFT": pd.DataFrame({"x": [1]})}
    p.symbols = ["AAPL", "MSFT"]
    p._pending_subscribe, p._pending_unsubscribe = set(), set()
    p._seed_error = None
    fetched = []
    monkeypatch.setattr(p, "_fetch_bars", lambda syms: (fetched.append(list(syms)) or {}, None))
    monkeypatch.setattr(p, "_store_bars", lambda bars, syms: None)

    p.sync_symbols(["aapl", "NFLX"])
    assert p.symbols == ["AAPL", "NFLX"] and fetched == [["NFLX"]]
    assert "MSFT" not in p._buffers
    assert p._pending_subscribe == {"NFLX"} and p._pending_unsubscribe == {"MSFT"}

    sent = []

    class _WS:
        def send(self, msg):
            sent.append(msg)

    p._flush_subscription_changes(_WS())
    assert sent == ['{"action": "subscribe", "bars": ["NFLX"]}', '{"action": "unsubscribe", "bars": ["MSFT"]}']
    assert not p._pending_subscribe and not p._pending_unsubscribe
