"""Breakout label construction.

Y_t = 1 if max(close_{t+1..t+N}) > R_t * (1 + delta) AND at least one of
the next N candles shows elevated relative volume, else 0.

This module is ONLY used at training time. It deliberately looks at
future candles (`shift(-i)`), which is why it lives outside
`features/engineering.py` (which must never see the future). Calling
this on live/inference data would be a leakage bug by construction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.config.settings import settings


def build_labels(
    df_with_features: pd.DataFrame,
    horizon: int | None = None,
    confirmation_threshold_pct: float | None = None,
    volume_multiple: float | None = None,
) -> pd.DataFrame:
    """Append a `label` column (0/1) to a feature DataFrame.

    Rows where the forward window runs past the end of the data (no full
    N-candle lookahead available) get `label = NaN` and must be dropped
    before training.
    """
    horizon = horizon or settings.prediction_horizon
    delta = confirmation_threshold_pct or settings.confirmation_threshold_pct
    vol_mult = volume_multiple or settings.volume_confirmation_multiple

    out = df_with_features.copy().reset_index(drop=True)
    n = len(out)

    future_max_close = pd.Series(np.nan, index=out.index)
    future_max_volume_ratio = pd.Series(np.nan, index=out.index)

    close = out["close"].values
    high = out["high"].values
    volume = out["volume"].values
    resistance = out["resistance"].values

    avg_volume_20 = out["volume"].rolling(20, min_periods=20).mean().values

    labels = np.full(n, np.nan)
    for t in range(n):
        end = t + horizon
        if end >= n or np.isnan(resistance[t]) or np.isnan(avg_volume_20[t]) or avg_volume_20[t] == 0:
            continue  # not enough future data / not enough history -> unlabeled
        window_high = high[t + 1 : end + 1]
        window_volume = volume[t + 1 : end + 1]
        breakout_price_condition = window_high.max() > resistance[t] * (1 + delta)
        breakout_volume_condition = (window_volume / avg_volume_20[t] >= vol_mult).any()
        labels[t] = float(breakout_price_condition and breakout_volume_condition)

    out["label"] = labels
    return out
