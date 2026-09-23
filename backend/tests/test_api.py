from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "model_status" in body


def test_opportunities_endpoint_shape():
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    body = resp.json()
    assert "opportunities" in body
    assert "summary" in body
    assert body["summary"]["stocks_monitored"] == len(body["opportunities"])


def test_stock_detail_unknown_symbol_returns_404():
    resp = client.get("/api/stock/NOTREAL")
    assert resp.status_code == 404


def test_stock_detail_known_symbol():
    resp = client.get("/api/stock/AAPL?limit=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert len(body["candles"]) == 60


def test_config_endpoint_exposes_tunables():
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    for key in ["resistance_window", "prediction_horizon", "confirmation_threshold_pct", "probability_alert_threshold"]:
        assert key in body
