from backend.config.settings import settings


def test_health_endpoint(api_client):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "model_status" in body


def test_health_reports_india_market(api_client):
    body = api_client.get("/api/health").json()
    info = body["market_info"]
    assert (info["market"], info["exchange"], info["currency_code"], info["timezone"]) == ("IN", "NSE", "INR", "Asia/Kolkata")
    assert body["currency_symbol"] == "\u20b9"
    assert body["market_data_provider"] == "yfinance"
    assert body["data_status"] == "delayed"          # never claimed "live"
    assert body["is_live_data"] is False
    assert info["session"]["session_open"] == "09:15" and info["session"]["session_close"] == "15:30"


def test_opportunities_endpoint_shape(api_client):
    resp = api_client.get("/api/opportunities")
    assert resp.status_code == 200
    body = resp.json()
    assert "opportunities" in body
    assert "summary" in body
    assert body["summary"]["stocks_monitored"] == len(body["opportunities"])
    assert body["market_info"]["market"] == "IN"


def test_opportunities_only_contain_indian_symbols_and_data_came_from_ns_tickers(api_client, fake_yahoo):
    body = api_client.get("/api/opportunities").json()
    symbols = [o["symbol"] for o in body["opportunities"]]
    assert symbols and all(s.endswith(".NS") for s in symbols)
    assert set(fake_yahoo.calls) == set(settings.watchlist_symbols)      # nothing else was requested
    # prices are INR-scale, not the 50-400 USD demo range
    assert max(o["current_price"] for o in body["opportunities"] if o["current_price"]) > 500


def test_explicit_market_is_preserved_or_rejected(api_client):
    assert api_client.get("/api/opportunities?market=IN").status_code == 200
    assert api_client.get("/api/opportunities?market=in").status_code == 200
    resp = api_client.get("/api/opportunities?market=US")
    assert resp.status_code == 400 and "not served" in resp.json()["detail"]
    assert api_client.get("/api/stock/RELIANCE.NS?market=US").status_code == 400


def test_stock_detail_unknown_symbol_returns_404(api_client):
    assert api_client.get("/api/stock/NOTREAL").status_code == 404


def test_stock_detail_us_ticker_is_not_served(api_client, fake_yahoo):
    resp = api_client.get("/api/stock/AAPL")           # would be AAPL.NS: not on the watchlist
    assert resp.status_code == 404
    assert "AAPL" not in fake_yahoo.calls and "AAPL.NS" not in fake_yahoo.calls
    assert api_client.get("/api/stock/BRK.B").status_code == 404


def test_stock_detail_known_symbol(api_client):
    symbol = settings.watchlist_symbols[0]
    resp = api_client.get(f"/api/stock/{symbol}?limit=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == symbol
    assert len(body["candles"]) == 60
    assert body["market_info"]["exchange"] == "NSE"


def test_stock_detail_accepts_bare_symbol_and_normalises(api_client):
    resp = api_client.get("/api/stock/reliance?limit=60")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "RELIANCE.NS"


def test_candle_timestamps_are_utc_and_map_to_ist_session(api_client):
    import pandas as pd

    candles = api_client.get("/api/stock/RELIANCE.NS?limit=100").json()["candles"]
    for c in candles:
        ts = pd.Timestamp(c["timestamp"])
        assert ts.utcoffset() == pd.Timedelta(0)
        local = ts.tz_convert("Asia/Kolkata")
        assert (9, 15) <= (local.hour, local.minute) <= (15, 30)


def test_provider_failure_is_reported_not_masked(api_client, fake_yahoo):
    fake_yahoo.data["SBIN.NS"] = RuntimeError("429 Too Many Requests")
    body = api_client.get("/api/opportunities").json()
    assert "SBIN.NS" in body["symbols_unavailable"]
    assert body["data_status"] == "partial"
    assert api_client.get("/api/stock/SBIN.NS").status_code == 503


def test_all_symbols_unavailable_reports_unavailable_not_demo(api_client, fake_yahoo):
    fake_yahoo.data.clear()                             # Yahoo knows none of them
    body = api_client.get("/api/opportunities").json()
    assert body["data_status"] == "unavailable"
    assert body["provider"] == "yfinance"
    assert all(o["breakout_probability"] is None for o in body["opportunities"])
    assert all(o["symbol"].endswith(".NS") for o in body["opportunities"])


def test_repeated_polling_is_stable(api_client):
    first = [o["symbol"] for o in api_client.get("/api/opportunities").json()["opportunities"]]
    second = [o["symbol"] for o in api_client.get("/api/opportunities").json()["opportunities"]]
    assert sorted(first) == sorted(second) and all(s.endswith(".NS") for s in second)


def test_config_endpoint_exposes_tunables(api_client):
    resp = api_client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    for key in ["resistance_window", "prediction_horizon", "confirmation_threshold_pct", "probability_alert_threshold"]:
        assert key in body
    assert body["market_info"]["market"] == "IN"
