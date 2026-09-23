"""Model persistence / registry.

Loads trained model bundles from disk. Training and inference are fully
separate processes: this module never trains anything, it only loads
what `training/train.py` already produced.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import joblib

from backend.config.settings import settings

logger = logging.getLogger(__name__)

MODEL_STORE = Path(__file__).resolve().parents[1] / settings.model_dir


class ModelUnavailableError(Exception):
    """Raised when no trained model artifact can be found on disk."""


class LoadedModel:
    def __init__(self, bundle: dict, pointer: dict):
        self.model = bundle["model"]
        self.calibrator = bundle.get("calibrator")
        self.scaler = bundle["scaler"]
        self.feature_columns = bundle["feature_columns"]
        self.metadata = bundle["metadata"]
        self.metrics = bundle.get("metrics", {})
        self.pointer = pointer

    def predict_proba(self, X):
        Xs = self.scaler.transform(X)
        proba_fn = self.calibrator.predict_proba if self.calibrator is not None else self.model.predict_proba
        return proba_fn(Xs)[:, 1]


_CACHE: dict[str, LoadedModel] = {}


def _read_pointer(model_name: str) -> Optional[dict]:
    pointer_path = MODEL_STORE / f"{model_name}_latest.json"
    if not pointer_path.exists():
        return None
    return json.loads(pointer_path.read_text())


def get_champion_pointer() -> Optional[dict]:
    champ_path = MODEL_STORE / "champion.json"
    if champ_path.exists():
        return json.loads(champ_path.read_text())
    return _read_pointer(settings.primary_model)


def load_model(model_name: str | None = None, use_cache: bool = True) -> LoadedModel:
    """Load a trained model bundle by name, or the champion if unset.

    Raises ModelUnavailableError (never crashes the caller silently) if
    nothing has been trained yet — callers should catch this and surface
    a "model unavailable" UI state rather than 500ing.
    """
    pointer = _read_pointer(model_name) if model_name else get_champion_pointer()
    if pointer is None:
        raise ModelUnavailableError(
            f"No trained model found for '{model_name or settings.primary_model}'. "
            "Run `python -m backend.training.train --model xgboost` first."
        )

    cache_key = f"{pointer['model_name']}:{pointer['version']}"
    if use_cache and cache_key in _CACHE:
        return _CACHE[cache_key]

    artifact_path = MODEL_STORE / pointer["artifact_path"]
    if not artifact_path.exists():
        raise ModelUnavailableError(f"Model artifact missing on disk: {artifact_path}")

    bundle = joblib.load(artifact_path)
    loaded = LoadedModel(bundle, pointer)
    _CACHE[cache_key] = loaded
    return loaded


def list_available_models() -> list[dict]:
    results = []
    for pointer_path in sorted(MODEL_STORE.glob("*_latest.json")):
        try:
            results.append(json.loads(pointer_path.read_text()))
        except Exception:  # pragma: no cover
            continue
    return results
