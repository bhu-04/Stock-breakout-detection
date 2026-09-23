"""Feature engineering pipeline.

Single reusable function used by BOTH the training pipeline and the live
inference pipeline, so there is no train/inference feature mismatch.

All indicators are computed using only data up to and including row t
(rolling windows, no `.shift(-n)` on inputs) to prevent leakage from
future candles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.config.settings import settings

FEATURE_COLUMNS = [
    "log_return",
    "price_change_pct",
    "high_low_range_pct",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "sma_10",
    "sma_30",
    "ema_10",
    "ema_30",
    "ma_crossover_signal",
    "atr_14",
    "bb_width",
    "hist_volatility_20",
    "rel_volume",
    "volume_spike",
    "dist_from_resistance_pct",
    "vwap_deviation_pct",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _bollinger_width(close: pd.Series, period: int = 20, n_std: float = 2.0) -> pd.Series:
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = mid + n_std * std
    lower = mid - n_std * std
    return (upper - lower) / mid.replace(0, np.nan)


def _vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    return pv.rolling(window, min_periods=1).sum() / df["volume"].rolling(window, min_periods=1).sum()


def compute_resistance(df: pd.DataFrame, window: int | None = None) -> pd.Series:
    """Rolling resistance = max high over the trailing `window` candles,
    EXCLUDING the current candle (shift(1)) so it never leaks the current
    bar's own high into its own feature/label.
    """
    window = window or settings.resistance_window
    return df["high"].rolling(window, min_periods=1).max().shift(1)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the full feature vector for every row of `df`.

    `df` must contain OHLCV columns sorted ascending by timestamp.
    Returns a new DataFrame with the original columns plus FEATURE_COLUMNS
    and a `resistance` column. Leading rows without enough history for a
    given indicator are NaN and should be dropped by the caller before
    training (see `training/labeling.py`).
    """
    out = df.copy().reset_index(drop=True)
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]

    out["log_return"] = np.log(close / close.shift(1))
    out["price_change_pct"] = close.pct_change()
    out["high_low_range_pct"] = (high - low) / close.replace(0, np.nan)

    out["rsi_14"] = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = macd_signal
    out["macd_hist"] = macd_hist

    out["sma_10"] = close.rolling(10, min_periods=10).mean()
    out["sma_30"] = close.rolling(30, min_periods=30).mean()
    out["ema_10"] = close.ewm(span=10, adjust=False).mean()
    out["ema_30"] = close.ewm(span=30, adjust=False).mean()
    out["ma_crossover_signal"] = np.sign(out["ema_10"] - out["ema_30"]).fillna(0)

    out["atr_14"] = _atr(high, low, close, 14)
    out["bb_width"] = _bollinger_width(close, 20)
    out["hist_volatility_20"] = out["log_return"].rolling(20, min_periods=20).std() * np.sqrt(20)

    avg_volume_20 = volume.rolling(20, min_periods=20).mean()
    out["rel_volume"] = volume / avg_volume_20.replace(0, np.nan)
    out["volume_spike"] = (out["rel_volume"] >= settings.volume_confirmation_multiple).astype(int)

    out["resistance"] = compute_resistance(out)
    out["dist_from_resistance_pct"] = (out["resistance"] - close) / out["resistance"].replace(0, np.nan)

    vwap = _vwap(out, window=20)
    out["vwap_deviation_pct"] = (close - vwap) / vwap.replace(0, np.nan)

    return out
