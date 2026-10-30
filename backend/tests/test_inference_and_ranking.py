import pytest

from backend.data.providers import DemoDataProvider, MarketDataProvider, ProviderUnavailableError
from backend.inference.pipeline import data_status_summary, run_inference_cycle
from backend.models.registry import ModelUnavailableError, load_model
from backend.ranking.rank import rank_opportunities


class _FlakyProvider(MarketDataProvider):
    """Test double: raises ProviderUnavailableError for one symbol, works for others."""

    is_live = True
    data_status = "delayed"
    name = "flaky"

    def __init__(self, fail_symbol: str):
        self._demo = DemoDataProvider()
        self._fail_symbol = fail_symbol

    def get_ohlcv(self, symbol, limit=500):
        if symbol == self._fail_symbol:
            raise ProviderUnavailableError("simulated rate limit")
        return self._demo.get_ohlcv(symbol, limit=limit)

    def get_latest_candle(self, symbol):
        if symbol == self._fail_symbol:
            raise ProviderUnavailableError("simulated rate limit")
        return self._demo.get_latest_candle(symbol)


def test_provider_failure_does_not_crash_inference_cycle():
    """A single symbol's provider failure must degrade gracefully (marked
    unavailable) rather than raising and taking down the whole endpoint."""
    provider = _FlakyProvider(fail_symbol="TCS.NS")
    results, _ = run_inference_cycle(["RELIANCE.NS", "TCS.NS", "INFY.NS"], provider)
    assert len(results) == 3
    failed = [r for r in results if r.symbol == "TCS.NS"]
    assert failed[0].error is not None and "provider_unavailable" in failed[0].error
    assert failed[0].breakout_probability is None

    status = data_status_summary(results, provider)
    assert status["data_status"] == "partial"
    assert "TCS.NS" in status["symbols_unavailable"]


def test_data_status_summary_all_unavailable():
    provider = _FlakyProvider(fail_symbol="RELIANCE.NS")
    results, _ = run_inference_cycle(["RELIANCE.NS"], provider)
    status = data_status_summary(results, provider)
    assert status["data_status"] == "unavailable"


def test_model_loads_without_retraining():
    """Assumes `python -m backend.training.train` has been run at least
    once (as it is in CI / the demo setup script). If no model has ever
    been trained, this should raise a clear, catchable error rather than
    crashing."""
    try:
        model = load_model()
    except ModelUnavailableError:
        pytest.skip("No trained model artifact present — run training first")
        return
    assert model.feature_columns
    assert "model_name" in model.metadata


def test_inference_cycle_runs_for_all_symbols():
    provider = DemoDataProvider()
    symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    results, _ = run_inference_cycle(symbols, provider)
    assert len(results) == len(symbols)
    for r in results:
        assert r.symbol in symbols
        assert r.current_price > 0


def test_ranking_sorts_by_probability_descending():
    provider = DemoDataProvider()
    results, _ = run_inference_cycle(["RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"], provider)
    ranked = rank_opportunities(results)
    scored = [r for r in ranked if r["breakout_probability"] is not None]
    probs = [r["breakout_probability"] for r in scored]
    assert probs == sorted(probs, reverse=True)
    # ranks assigned 1..N with no gaps for scored rows
    assert [r["rank"] for r in scored] == list(range(1, len(scored) + 1))


def test_ranking_handles_missing_model_gracefully():
    """If a symbol's inference has no probability (e.g. model unavailable),
    ranking must not crash and must flag it rather than silently drop it."""
    from backend.inference.pipeline import SymbolInference
    from datetime import datetime, timezone

    fake = SymbolInference(
        symbol="ZZZZ",
        timestamp=datetime.now(timezone.utc),
        breakout_probability=None,
        current_price=100.0,
        rsi=50.0,
        relative_volume=1.0,
        trend_signal="Model Unavailable",
        distance_from_resistance_pct=0.0,
        resistance=100.0,
        atr=1.0,
        macd_hist=0.0,
        model_available=False,
        error="model_unavailable",
    )
    ranked = rank_opportunities([fake])
    assert ranked[0]["rank"] is None
    assert ranked[0]["breakout_probability"] is None
    assert ranked[0]["symbol"] == "ZZZZ"
