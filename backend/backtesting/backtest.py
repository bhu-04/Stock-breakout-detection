"""Basic historical backtesting.

Evaluates the breakout-detection approach against historical (demo) data.
Deliberately separates:
  - MODEL PERFORMANCE (classification metrics — computed in training/train.py)
  - STRATEGY PERFORMANCE (what happens if you actually traded the signals)

These are never conflated: a model can have a solid ROC-AUC while a naive
trading rule built on top of it still loses money after costs/slippage,
and this module surfaces that honestly instead of hiding it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from backend.config.settings import settings
from backend.data.providers import DemoDataProvider
from backend.features.engineering import FEATURE_COLUMNS, build_features
from backend.models.registry import LoadedModel, ModelUnavailableError, load_model
from backend.training.labeling import build_labels


@dataclass
class StrategyMetrics:
    n_signals: int
    n_confirmed_breakouts: int
    false_breakout_rate: float
    avg_detection_lead_time: float
    cumulative_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    evaluated: bool
    note: str = ""


def _max_drawdown(equity_curve: np.ndarray) -> float:
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min()) if len(drawdown) else 0.0


def _sharpe(returns: np.ndarray, periods_per_year: int = 252 * 78) -> float:
    # 78 ~= number of 5-min candles in a US trading day; used only to
    # annualize a demo-data Sharpe estimate, not a claim about real markets.
    if returns.std(ddof=1) == 0 or len(returns) < 2:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / returns.std(ddof=1))


def backtest_symbol(
    symbol: str, model: LoadedModel, probability_threshold: float, candles: int = 1200
) -> StrategyMetrics:
    provider = DemoDataProvider()
    raw = provider.get_ohlcv(symbol, limit=candles)
    feats = build_features(raw)
    labeled = build_labels(feats)
    df = labeled.dropna(subset=FEATURE_COLUMNS + ["label"]).reset_index(drop=True)

    if df.empty:
        return StrategyMetrics(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, evaluated=False, note="insufficient data")

    X = df[FEATURE_COLUMNS].astype(float)
    df["proba"] = model.predict_proba(X)
    signals = df[df["proba"] >= probability_threshold].copy()

    n_signals = len(signals)
    n_confirmed = int(signals["label"].sum())
    false_rate = float(1 - signals["label"].mean()) if n_signals > 0 else 0.0

    # detection lead time: candles between signal and first future candle
    # that actually crosses the resistance+delta threshold (only for
    # confirmed breakouts, since unconfirmed ones never cross)
    lead_times = []
    horizon = settings.prediction_horizon
    delta = settings.confirmation_threshold_pct
    close_arr, high_arr, resistance_arr = df["close"].values, df["high"].values, df["resistance"].values
    for idx in signals.index[signals["label"] == 1]:
        target = resistance_arr[idx] * (1 + delta)
        for k in range(1, horizon + 1):
            j = idx + k
            if j >= len(df):
                break
            if high_arr[j] > target:
                lead_times.append(k)
                break
    avg_lead_time = float(np.mean(lead_times)) if lead_times else 0.0

    # Simple strategy: enter at signal close, exit at close of candle
    # `horizon` steps later, flat (equal) position sizing, no leverage/costs.
    #
    # NOTE ON METHODOLOGY: breakout signals fired on consecutive candles
    # overlap heavily (the same setup can re-trigger every bar within its
    # own N-candle horizon). Treating overlapping signals as sequential,
    # fully-compounded trades (naive cumprod of an equity curve) massively
    # overstates returns, since it implicitly assumes 100% of capital is
    # reinvested into many simultaneous, correlated positions. To avoid
    # reporting an inflated/misleading number, each trade here is treated
    # as an independent, equally-weighted allocation and returns are
    # averaged (not compounded) into a single per-trade cumulative figure.
    trade_returns = []
    for idx in signals.index:
        exit_idx = idx + horizon
        if exit_idx < len(df):
            trade_returns.append((close_arr[exit_idx] - close_arr[idx]) / close_arr[idx])

    if trade_returns:
        trade_returns = np.array(trade_returns)
        # equity curve for drawdown: equal-weighted capital per trade,
        # applied sequentially in signal order (not compounded)
        equity = 1 + np.cumsum(trade_returns) / max(1, len(trade_returns))
        cumulative_return_pct = float(trade_returns.mean() * 100)
        max_dd_pct = _max_drawdown(equity) * 100
        sharpe = _sharpe(trade_returns, periods_per_year=252)  # per-trade, not per-candle
    else:
        cumulative_return_pct, max_dd_pct, sharpe = 0.0, 0.0, 0.0

    return StrategyMetrics(
        n_signals=n_signals,
        n_confirmed_breakouts=n_confirmed,
        false_breakout_rate=round(false_rate, 4),
        avg_detection_lead_time=round(avg_lead_time, 2),
        cumulative_return_pct=round(cumulative_return_pct, 3),
        max_drawdown_pct=round(max_dd_pct, 3),
        sharpe_ratio=round(sharpe, 3),
        evaluated=True,
        note="Backtested on DEMO/SIMULATED data only — not real historical market data.",
    )


def run_backtest(symbols: list[str] | None = None, probability_threshold: float | None = None) -> dict:
    symbols = symbols or settings.watchlist_symbols
    probability_threshold = probability_threshold or settings.probability_alert_threshold

    try:
        model = load_model()
    except ModelUnavailableError as exc:
        return {"evaluated": False, "note": str(exc), "per_symbol": {}, "aggregate": None}

    per_symbol = {}
    for symbol in symbols:
        per_symbol[symbol] = asdict(backtest_symbol(symbol, model, probability_threshold))

    all_signals = sum(v["n_signals"] for v in per_symbol.values())
    all_confirmed = sum(v["n_confirmed_breakouts"] for v in per_symbol.values())
    avg_return = float(np.mean([v["cumulative_return_pct"] for v in per_symbol.values()])) if per_symbol else 0.0
    avg_sharpe = float(np.mean([v["sharpe_ratio"] for v in per_symbol.values()])) if per_symbol else 0.0
    worst_dd = float(np.min([v["max_drawdown_pct"] for v in per_symbol.values()])) if per_symbol else 0.0

    aggregate = {
        "total_signals": all_signals,
        "total_confirmed_breakouts": all_confirmed,
        "false_breakout_rate": round(1 - (all_confirmed / all_signals), 4) if all_signals else None,
        "avg_cumulative_return_pct": round(avg_return, 3),
        "avg_sharpe_ratio": round(avg_sharpe, 3),
        "worst_max_drawdown_pct": round(worst_dd, 3),
    }

    return {
        "evaluated": True,
        "note": "MODEL PERFORMANCE (classification) and STRATEGY PERFORMANCE (trading) are reported separately. "
        "This backtest uses DEMO/SIMULATED data — results are not indicative of real-market performance.",
        "model": {"name": model.metadata["model_name"], "version": model.metadata["version"], "classification_metrics": model.metrics},
        "per_symbol": per_symbol,
        "aggregate": aggregate,
    }
