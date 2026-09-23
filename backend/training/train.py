"""Model training pipeline.

Usage (from repo root):
    python -m backend.training.train --model xgboost
    python -m backend.training.train --model all   # trains & compares all 4

Produces, per model, a versioned artifact bundle in `model_store/`:
    <model_name>_<version>.joblib   -> {"model": ..., "calibrator": ..., "scaler": ...,
                                         "feature_columns": [...], "metadata": {...}}
    <model_name>_latest.json        -> pointer + metrics for the dashboard/API
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from backend.config.settings import settings
from backend.data.providers import DemoDataProvider
from backend.features.engineering import FEATURE_COLUMNS, build_features
from backend.training.labeling import build_labels

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_STORE = Path(__file__).resolve().parents[1] / settings.model_dir
MODEL_STORE.mkdir(parents=True, exist_ok=True)


@dataclass
class EvalMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    pr_auc: float
    n_test: int
    positive_rate_test: float


def build_training_dataset(symbols: list[str] | None = None, candles_per_symbol: int = 1200) -> pd.DataFrame:
    """Pull demo OHLCV for each symbol, build features + labels, concatenate.

    NOTE: uses the demo provider for reproducible offline training data.
    Swapping to a historical live data source only requires changing this
    function's data source; downstream code is unaffected.
    """
    symbols = symbols or settings.watchlist_symbols
    provider = DemoDataProvider()
    frames = []
    for symbol in symbols:
        raw = provider.get_ohlcv(symbol, limit=candles_per_symbol)
        feats = build_features(raw)
        labeled = build_labels(feats)
        labeled["symbol"] = symbol
        frames.append(labeled)
    full = pd.concat(frames, ignore_index=True)
    full = full.dropna(subset=FEATURE_COLUMNS + ["label"]).reset_index(drop=True)
    return full


def time_aware_split(df: pd.DataFrame):
    """Per-symbol chronological split (train / val / test) — no shuffling,
    so no future information leaks into the training set.
    """
    train_frames, val_frames, test_frames = [], [], []
    for _, group in df.groupby("symbol", sort=False):
        group = group.sort_values("timestamp").reset_index(drop=True)
        n = len(group)
        train_end = int(n * settings.train_test_split_ratio)
        val_end = train_end + int(n * settings.validation_split_ratio)
        train_frames.append(group.iloc[:train_end])
        val_frames.append(group.iloc[train_end:val_end])
        test_frames.append(group.iloc[val_end:])
    return (
        pd.concat(train_frames, ignore_index=True),
        pd.concat(val_frames, ignore_index=True),
        pd.concat(test_frames, ignore_index=True),
    )


def _build_estimator(model_name: str, scale_pos_weight: float):
    if model_name == "xgboost":
        import xgboost as xgb

        return xgb.XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            random_state=42,
        )
    if model_name == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=-1,
            num_leaves=31,
            learning_rate=0.05,
            class_weight="balanced",
            random_state=42,
            verbosity=-1,
        )
    if model_name == "random_forest":
        return RandomForestClassifier(
            n_estimators=300, max_depth=8, class_weight="balanced", random_state=42, n_jobs=-1
        )
    if model_name == "logistic_regression":
        return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    raise ValueError(f"Unknown model: {model_name}")


def train_one(model_name: str, train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame) -> dict:
    X_train, y_train = train_df[FEATURE_COLUMNS], train_df["label"]
    X_val, y_val = val_df[FEATURE_COLUMNS], val_df["label"]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df["label"]

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)

    n_pos = max(1, int(y_train.sum()))
    n_neg = max(1, len(y_train) - n_pos)
    scale_pos_weight = n_neg / n_pos

    base_estimator = _build_estimator(model_name, scale_pos_weight)
    base_estimator.fit(X_train_s, y_train)

    # Probability calibration (sigmoid/Platt scaling) using the held-out
    # validation split so calibration doesn't see training or test data.
    calibrator = None
    try:
        calibrator = CalibratedClassifierCV(base_estimator, method="sigmoid", cv="prefit")
        calibrator.fit(X_val_s, y_val)
        proba_fn = calibrator.predict_proba
    except Exception as exc:  # pragma: no cover
        logger.warning("Calibration failed for %s, using raw probabilities: %s", model_name, exc)
        proba_fn = base_estimator.predict_proba

    test_proba = proba_fn(X_test_s)[:, 1]
    test_pred = (test_proba >= 0.5).astype(int)

    metrics = EvalMetrics(
        accuracy=float(accuracy_score(y_test, test_pred)),
        precision=float(precision_score(y_test, test_pred, zero_division=0)),
        recall=float(recall_score(y_test, test_pred, zero_division=0)),
        f1=float(f1_score(y_test, test_pred, zero_division=0)),
        roc_auc=float(roc_auc_score(y_test, test_proba)) if y_test.nunique() > 1 else float("nan"),
        pr_auc=float(average_precision_score(y_test, test_proba)) if y_test.nunique() > 1 else float("nan"),
        n_test=int(len(y_test)),
        positive_rate_test=float(y_test.mean()),
    )

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = {
        "model": base_estimator,
        "calibrator": calibrator,
        "scaler": scaler,
        "feature_columns": FEATURE_COLUMNS,
        "metadata": {
            "model_name": model_name,
            "version": version,
            "trained_at": version,
            "n_train": int(len(train_df)),
            "n_val": int(len(val_df)),
            "n_test": int(len(test_df)),
            "feature_count": len(FEATURE_COLUMNS),
            "config": {
                "prediction_horizon": settings.prediction_horizon,
                "confirmation_threshold_pct": settings.confirmation_threshold_pct,
                "volume_confirmation_multiple": settings.volume_confirmation_multiple,
                "resistance_window": settings.resistance_window,
            },
        },
        "metrics": asdict(metrics),
    }

    artifact_path = MODEL_STORE / f"{model_name}_{version}.joblib"
    joblib.dump(bundle, artifact_path)

    pointer = {
        "model_name": model_name,
        "version": version,
        "artifact_path": str(artifact_path.name),
        "trained_at": version,
        "feature_count": len(FEATURE_COLUMNS),
        "metrics": asdict(metrics),
        "evaluated": True,
    }
    (MODEL_STORE / f"{model_name}_latest.json").write_text(json.dumps(pointer, indent=2))
    logger.info("Trained %s -> %s | ROC-AUC=%.3f PR-AUC=%.3f", model_name, artifact_path.name, metrics.roc_auc, metrics.pr_auc)
    return pointer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="xgboost",
        choices=["xgboost", "lightgbm", "random_forest", "logistic_regression", "all"],
    )
    parser.add_argument("--candles", type=int, default=1200, help="Candles per symbol for training data")
    args = parser.parse_args()

    logger.info("Building training dataset from demo data (%d candles/symbol)...", args.candles)
    dataset = build_training_dataset(candles_per_symbol=args.candles)
    logger.info("Dataset: %d rows, positive rate=%.3f", len(dataset), dataset["label"].mean())

    train_df, val_df, test_df = time_aware_split(dataset)
    logger.info("Split -> train=%d val=%d test=%d", len(train_df), len(val_df), len(test_df))

    models = ["xgboost", "lightgbm", "random_forest", "logistic_regression"] if args.model == "all" else [args.model]
    results = {}
    for m in models:
        results[m] = train_one(m, train_df, val_df, test_df)

    # Point "champion" (used by inference if primary_model isn't explicitly set)
    best = max(results.values(), key=lambda r: r["metrics"]["roc_auc"] if not np.isnan(r["metrics"]["roc_auc"]) else -1)
    (MODEL_STORE / "champion.json").write_text(json.dumps(best, indent=2))
    logger.info("Champion model: %s (ROC-AUC=%.3f)", best["model_name"], best["metrics"]["roc_auc"])


if __name__ == "__main__":
    main()
