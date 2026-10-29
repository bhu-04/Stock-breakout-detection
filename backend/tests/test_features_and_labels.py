"""Unit tests: feature calculations, breakout labeling, preprocessing.

Run with: pytest backend/tests -v
"""
import numpy as np
import pandas as pd
import pytest

from backend.data.providers import DemoDataProvider
from backend.features.engineering import FEATURE_COLUMNS, build_features, compute_resistance
from backend.training.labeling import build_labels


@pytest.fixture(scope="module")
def raw_ohlcv():
    return DemoDataProvider().get_ohlcv("TEST", limit=300)


def test_demo_provider_returns_expected_columns(raw_ohlcv):
    assert list(raw_ohlcv.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(raw_ohlcv) == 300
    assert (raw_ohlcv["close"] > 0).all()
    assert (raw_ohlcv["volume"] > 0).all()


def test_demo_provider_deterministic_per_symbol():
    p = DemoDataProvider()
    a = p.get_ohlcv("RELIANCE.NS", limit=100)
    b = p.get_ohlcv("RELIANCE.NS", limit=100)
    pd.testing.assert_frame_equal(a, b)


def test_build_features_adds_all_columns(raw_ohlcv):
    feats = build_features(raw_ohlcv)
    for col in FEATURE_COLUMNS:
        assert col in feats.columns
    # tail rows (after warm-up windows) should be fully populated
    assert not feats[FEATURE_COLUMNS].tail(10).isna().any().any()


def test_resistance_excludes_current_bar():
    df = pd.DataFrame({"high": [10, 20, 5, 5, 5]})
    res = compute_resistance(df, window=3)
    # row 1's resistance must be based only on row 0 (shifted), not itself
    assert res.iloc[1] == 10
    # row 2's resistance is max(high[0:2]) = 20, must NOT include its own high (5)
    assert res.iloc[2] == 20


def test_no_lookahead_in_features(raw_ohlcv):
    """Features computed on a truncated series must match features computed
    on the full series, up to the truncation point — i.e. no feature at
    time t depends on data after t."""
    full = build_features(raw_ohlcv)
    truncated = build_features(raw_ohlcv.iloc[:150])
    common = FEATURE_COLUMNS
    pd.testing.assert_frame_equal(
        full[common].iloc[:150].reset_index(drop=True),
        truncated[common].reset_index(drop=True),
        check_exact=False,
        atol=1e-8,
    )


def test_build_labels_marks_tail_as_unlabeled(raw_ohlcv):
    feats = build_features(raw_ohlcv)
    labeled = build_labels(feats, horizon=10)
    # last `horizon` rows can't have a full forward window -> NaN label
    assert labeled["label"].iloc[-10:].isna().all()


def test_build_labels_binary_values(raw_ohlcv):
    feats = build_features(raw_ohlcv)
    labeled = build_labels(feats, horizon=10)
    valid = labeled["label"].dropna()
    assert set(valid.unique()).issubset({0.0, 1.0})


def test_build_labels_respects_threshold_direction(raw_ohlcv):
    """A higher confirmation threshold should never produce MORE positive
    labels than a lower one (breakouts get strictly harder to confirm)."""
    feats = build_features(raw_ohlcv)
    loose = build_labels(feats, horizon=10, confirmation_threshold_pct=0.001)
    strict = build_labels(feats, horizon=10, confirmation_threshold_pct=0.05)
    assert strict["label"].sum() <= loose["label"].sum()
