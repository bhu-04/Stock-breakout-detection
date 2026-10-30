"""FastAPI application - one backend serving the India (IN) and US markets.

Every market-aware endpoint takes an explicit `market` (IN | US). When it is
omitted on a READ it falls back to the default market (settings.market, India);
WRITES always require it. A symbol is only ever interpreted against the market it
was sent for, and a market's data is only ever fetched through that market's own
provider instance.

Endpoints:
  GET    /api/markets            -> supported markets: labels, currency, time zone, live session state
  GET    /api/health?market=     -> system/status for a market
  GET    /api/watchlist?market=  -> a market's watchlist (defaults + user edits)
  POST   /api/watchlist          -> add a symbol {market, symbol} (validated against the data provider)
  DELETE /api/watchlist/{symbol}?market=  -> remove a symbol
  POST   /api/watchlist/reset    -> restore a market's default watchlist {market}
  GET    /api/opportunities?market=  -> ranked breakout list for the market's whole watchlist
  GET    /api/stock/{symbol}?market= -> candlestick history + detail view data
  GET  /api/model/info        -> current champion model metadata + metrics
  GET  /api/models            -> all trained model pointers (for comparison)
  POST /api/train             -> trigger training (blocking; intended for small demo datasets)
  GET  /api/backtest          -> run historical backtest
  GET  /api/config            -> current tunable configuration (read-only)
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.backtesting.backtest import run_backtest
from backend.config.market import MARKETS, InvalidSymbolError, MarketSpec, get_market, qualify_symbol, session_status
from backend.config.settings import settings
from backend.data.providers import (
    PROVIDER_MARKETS,
    MarketDataProvider,
    ProviderUnavailableError,
    SymbolNotFoundError,
    get_provider,
)
from backend.data.watchlist_store import WatchlistError, get_store
from backend.features.engineering import build_features
from backend.inference.pipeline import data_status_summary, run_inference_cycle
from backend.models.registry import ModelUnavailableError, list_available_models, load_model
from backend.ranking.rank import rank_opportunities
from backend.training.train import build_training_dataset, time_aware_split, train_one

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Stock Breakout Detection", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now(timezone.utc)
_update_counts: dict[str, int] = {code: 0 for code in MARKETS}      # per market
_providers: dict[str, MarketDataProvider] = {}                        # one instance per market, built lazily
_state_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
def _resolve_market(market: str | None) -> MarketSpec:
    """Validate a market identifier. Unknown -> 400; omitted -> the default market."""
    if market is None or not market.strip():
        return settings.market_spec
    try:
        return get_market(market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _provider_for(code: str) -> MarketDataProvider:
    """The provider instance dedicated to `code` (never shared across markets)."""
    with _state_lock:
        provider = _providers.get(code)
        if provider is None:
            provider = _providers[code] = get_provider(code, get_store().symbols(code))
        return provider


def _market_info(code: str) -> dict:
    """Everything the UI needs to label/format one market. Every response carries it so
    the frontend never has to guess (or default to) a market/currency."""
    spec = get_market(code)
    exchange = settings.exchange_for(code)
    return {
        "market": spec.code,
        "market_name": spec.name,
        "exchange": exchange,
        "label": spec.badge_label(exchange),
        "option_label": spec.option_label(exchange),
        "currency_code": spec.currency_code,
        "currency_symbol": spec.currency_symbol,
        "timezone": spec.timezone,
        "locale": spec.locale,
        "example_symbols": list(spec.example_symbols),
        "session": session_status(spec, holidays=settings.holidays_for(code)),
    }


def _watchlist_response(code: str) -> dict:
    return {**get_store().describe(code), "readonly": settings.watchlist_readonly, "market_info": _market_info(code)}


def _require_writable() -> None:
    if settings.watchlist_readonly:
        raise HTTPException(status_code=403, detail="Watchlist editing is disabled on this deployment (WATCHLIST_READONLY)")


def _http_from_store(exc: WatchlistError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ------------------------------------------------------------------ markets / health
@app.get("/api/markets")
def markets():
    store = get_store()
    out = []
    for code in MARKETS:
        supported = code in PROVIDER_MARKETS.get(settings.market_data_provider.strip().lower(), ())
        out.append(
            {
                **_market_info(code),
                "watchlist_size": len(store.symbols(code)),
                "data_provider": settings.market_data_provider,
                "provider_supports_market": supported,
            }
        )
    return {"default_market": settings.market_spec.code, "markets": out}


@app.get("/api/health")
def health(market: str | None = Query(None, description="IN | US; defaults to the default market")):
    spec = _resolve_market(market)
    code = spec.code
    provider = _provider_for(code)
    model_status = "unavailable"
    try:
        load_model()
        model_status = "loaded"
    except ModelUnavailableError:
        pass

    return {
        "status": "ok",
        "market": code,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds(),
        "market_data_provider": provider.name,
        "is_live_data": provider.is_live,
        "data_status": provider.data_status,
        "data_feed": getattr(provider, "feed", None),
        "model_status": model_status,
        "update_count": _update_counts[code],
        "watchlist_size": len(get_store().symbols(code)),
        "currency_symbol": spec.currency_symbol,
        "market_info": _market_info(code),
        "config_warnings": settings.config_warnings,
    }


# ------------------------------------------------------------------ watchlists
class WatchlistAdd(BaseModel):
    market: str
    symbol: str


class WatchlistReset(BaseModel):
    market: str


@app.get("/api/watchlist")
def get_watchlist(market: str | None = Query(None, description="IN | US; defaults to the default market")):
    return _watchlist_response(_resolve_market(market).code)


@app.post("/api/watchlist")
def add_to_watchlist(body: WatchlistAdd):
    """Add a symbol to ONE market's watchlist after checking the data provider can serve it.

    Failure modes are deliberately distinct: 422 = the symbol is invalid / unknown / has too
    little history (the user should fix it); 409 = already listed; 503 = we could not reach
    the provider to verify (try again - nothing was added and nothing is assumed valid)."""
    _require_writable()
    spec = _resolve_market(body.market)
    code = spec.code
    exchange = settings.exchange_for(code)
    store = get_store()

    try:
        qualified = qualify_symbol(body.symbol, spec, exchange)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=422, detail=f"Not a valid {spec.name} symbol: {exc}") from exc

    if qualified in store.symbols(code):                       # cheap checks before any network call
        raise HTTPException(status_code=409, detail=f"{qualified} is already in the {spec.name} watchlist")
    if len(store.symbols(code)) >= store.max_size:
        raise HTTPException(status_code=422, detail=f"The {spec.name} watchlist is limited to {store.max_size} symbols")

    provider = _provider_for(code)
    try:
        candles = provider.get_ohlcv(qualified, limit=settings.min_history_candles * 5)
    except SymbolNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No market data found for {qualified} on {spec.badge_label(exchange)}. Check the spelling; "
                f"symbols are interpreted for the selected market, so switch markets to add a stock listed elsewhere. ({exc})"
            ),
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not verify {qualified} right now because the data provider is unavailable or rate-limited. "
                   f"Nothing was added - please try again shortly. ({exc})",
        ) from exc
    if len(candles) < settings.min_history_candles:
        raise HTTPException(
            status_code=422,
            detail=f"{qualified} returned only {len(candles)} candles; at least {settings.min_history_candles} "
                   f"are needed to compute breakout indicators.",
        )

    try:
        store.add(code, qualified)
    except WatchlistError as exc:
        raise _http_from_store(exc) from exc
    provider.sync_symbols(store.symbols(code))
    return {**_watchlist_response(code), "added": qualified, "company_name": provider.company_name(qualified)}


@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str, market: str = Query(..., description="IN | US")):
    _require_writable()
    spec = _resolve_market(market)
    try:
        qualified = qualify_symbol(symbol, spec, settings.exchange_for(spec.code))
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=422, detail=f"Not a valid {spec.name} symbol: {exc}") from exc
    try:
        get_store().remove(spec.code, qualified)
    except WatchlistError as exc:
        raise _http_from_store(exc) from exc
    _provider_for(spec.code).sync_symbols(get_store().symbols(spec.code))
    return {**_watchlist_response(spec.code), "removed": qualified}


@app.post("/api/watchlist/reset")
def reset_watchlist(body: WatchlistReset):
    """Restore ONE market's default watchlist. The other market is untouched."""
    _require_writable()
    spec = _resolve_market(body.market)
    get_store().reset(spec.code)
    _provider_for(spec.code).sync_symbols(get_store().symbols(spec.code))
    return _watchlist_response(spec.code)


# ------------------------------------------------------------------ analysis
@app.get("/api/opportunities")
def opportunities(market: str | None = Query(None, description="IN | US; defaults to the default market")):
    spec = _resolve_market(market)
    code = spec.code
    store = get_store()
    desc = store.describe(code)
    items = desc["symbols"]
    symbols = [i["symbol"] for i in items]                       # the WHOLE active watchlist, never truncated
    provider = _provider_for(code)
    provider.sync_symbols(symbols)

    results, model_meta = run_inference_cycle(symbols, provider)
    ranked = rank_opportunities(results)
    is_default = {i["symbol"]: i["is_default"] for i in items}
    for row in ranked:
        row["is_default"] = is_default.get(row["symbol"], False)
    status = data_status_summary(results, provider)
    with _state_lock:
        _update_counts[code] += 1
        update_count = _update_counts[code]

    n_alerts = sum(1 for r in ranked if r["is_alert"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": code,
        "is_live_data": provider.is_live,
        "data_status": status["data_status"],
        "data_feed": getattr(provider, "feed", None),
        "data_latency_ms": status["latency_ms"],
        "symbols_unavailable": status["symbols_unavailable"],
        "symbol_errors": status["symbol_errors"],
        "provider": provider.name,
        "market_info": _market_info(code),
        "model": model_meta,
        "watchlist": {
            "size": len(items),
            "customized": desc["customized"],
            "added_count": sum(1 for i in items if not i["is_default"]),
            "removed_defaults": desc["removed_defaults"],
            "max_size": store.max_size,
            "readonly": settings.watchlist_readonly,
        },
        "summary": {
            "stocks_monitored": len(ranked),
            "high_probability_opportunities": n_alerts,
            "live_update_count": update_count,
            "alert_threshold": settings.probability_alert_threshold,
            "failed_symbols": len(status["symbol_errors"]),
        },
        "opportunities": ranked,
    }


@app.get("/api/stock/{symbol}")
def stock_detail(
    symbol: str,
    limit: int = Query(200, ge=30, le=1000),
    market: str | None = Query(None, description="IN | US; defaults to the default market"),
):
    spec = _resolve_market(market)
    code = spec.code
    try:
        symbol = qualify_symbol(symbol, spec, settings.exchange_for(code))
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=404, detail=f"Invalid symbol for {spec.name}: {exc}") from exc
    if symbol not in get_store().symbols(code):
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the {spec.name} watchlist")

    provider = _provider_for(code)
    try:
        raw = provider.get_ohlcv(symbol, limit=limit)
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Data unavailable for {symbol}: {exc}") from exc
    feats = build_features(raw)
    latest = feats.iloc[-1]

    model_meta = None
    breakout_probability = None
    try:
        model = load_model()
        model_meta = {**model.metadata, "metrics": model.metrics}
        from backend.features.engineering import FEATURE_COLUMNS

        if not feats[FEATURE_COLUMNS].iloc[-1].isna().any():
            X = latest[FEATURE_COLUMNS].to_frame().T.astype(float)
            breakout_probability = round(float(model.predict_proba(X)[0]), 4)
    except ModelUnavailableError:
        pass

    candles = [
        {
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": float(row["volume"]),
        }
        for _, row in feats.iterrows()
    ]

    return {
        "symbol": symbol,
        "market": code,
        "is_live_data": provider.is_live,
        "data_status": provider.data_status,
        "data_feed": getattr(provider, "feed", None),
        "provider": provider.name,
        "market_info": _market_info(code),
        "candles": candles,
        "resistance": round(float(latest["resistance"]), 2) if latest["resistance"] == latest["resistance"] else None,
        "breakout_confirmation_price": (
            round(float(latest["resistance"]) * (1 + settings.confirmation_threshold_pct), 2)
            if latest["resistance"] == latest["resistance"]
            else None
        ),
        "breakout_probability": breakout_probability,
        "indicators": {
            "rsi_14": round(float(latest["rsi_14"]), 2) if latest["rsi_14"] == latest["rsi_14"] else None,
            "macd": round(float(latest["macd"]), 4) if latest["macd"] == latest["macd"] else None,
            "macd_signal": round(float(latest["macd_signal"]), 4) if latest["macd_signal"] == latest["macd_signal"] else None,
            "atr_14": round(float(latest["atr_14"]), 3) if latest["atr_14"] == latest["atr_14"] else None,
            "relative_volume": round(float(latest["rel_volume"]), 2) if latest["rel_volume"] == latest["rel_volume"] else None,
            "vwap_deviation_pct": round(float(latest["vwap_deviation_pct"]) * 100, 2) if latest["vwap_deviation_pct"] == latest["vwap_deviation_pct"] else None,
        },
        "model": model_meta,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/model/info")
def model_info():
    try:
        model = load_model()
    except ModelUnavailableError as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, "metadata": model.metadata, "metrics": model.metrics, "pointer": model.pointer}


@app.get("/api/models")
def models():
    return {"models": list_available_models()}


@app.post("/api/train")
def train(model: str = Query("xgboost", pattern="^(xgboost|lightgbm|random_forest|logistic_regression)$"), candles: int = Query(1200, ge=200, le=5000)):
    logger.info("Training triggered via API: model=%s candles=%d", model, candles)
    dataset = build_training_dataset(candles_per_symbol=candles)
    if dataset.empty:
        raise HTTPException(status_code=500, detail="Training dataset is empty")
    train_df, val_df, test_df = time_aware_split(dataset)
    pointer = train_one(model, train_df, val_df, test_df)

    import json
    from pathlib import Path

    from backend.models.registry import MODEL_STORE

    champ_path = MODEL_STORE / "champion.json"
    if not champ_path.exists():
        champ_path.write_text(json.dumps(pointer, indent=2))

    return {"trained": True, "pointer": pointer}


@app.get("/api/backtest")
def backtest(threshold: float = Query(None, ge=0.0, le=1.0)):
    result = run_backtest(probability_threshold=threshold)
    return result


@app.get("/api/config")
def config():
    return {
        "resistance_window": settings.resistance_window,
        "prediction_horizon": settings.prediction_horizon,
        "confirmation_threshold_pct": settings.confirmation_threshold_pct,
        "volume_confirmation_multiple": settings.volume_confirmation_multiple,
        "probability_alert_threshold": settings.probability_alert_threshold,
        "watchlist": settings.watchlist_symbols,        # default market's DEFAULT list (training / backtest)
        "watchlists": {code: get_store().symbols(code) for code in MARKETS},
        "market_data_provider": settings.market_data_provider,
        "default_market": settings.market_spec.code,
        "market_info": _market_info(settings.market_spec.code),
        "config_warnings": settings.config_warnings,
        "refresh_interval_seconds": settings.refresh_interval_seconds,
    }