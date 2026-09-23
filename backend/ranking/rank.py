"""Opportunity ranking.

Sorts inference results by breakout probability (primary key), attaches
rank and alert flag. Kept intentionally simple (no hidden weighting) so
the ranking is transparent and matches what the dashboard describes.
"""
from __future__ import annotations

from backend.config.settings import settings
from backend.inference.pipeline import SymbolInference


def rank_opportunities(results: list[SymbolInference]) -> list[dict]:
    scored = [r for r in results if r.breakout_probability is not None]
    unscored = [r for r in results if r.breakout_probability is None]

    scored.sort(key=lambda r: r.breakout_probability, reverse=True)

    ranked = []
    for i, r in enumerate(scored, start=1):
        ranked.append(
            {
                "rank": i,
                "symbol": r.symbol,
                "breakout_probability": round(r.breakout_probability, 4),
                "current_price": round(r.current_price, 2),
                "rsi": round(r.rsi, 1),
                "relative_volume": round(r.relative_volume, 2),
                "trend_signal": r.trend_signal,
                "distance_from_resistance_pct": round(r.distance_from_resistance_pct * 100, 2),
                "resistance": round(r.resistance, 2),
                "atr": round(r.atr, 3),
                "last_updated": r.timestamp.isoformat(),
                "is_alert": r.breakout_probability >= settings.probability_alert_threshold,
                "model_available": True,
            }
        )

    for r in unscored:
        ranked.append(
            {
                "rank": None,
                "symbol": r.symbol,
                "breakout_probability": None,
                "current_price": round(r.current_price, 2) if r.current_price == r.current_price else None,
                "rsi": round(r.rsi, 1) if r.rsi == r.rsi else None,
                "relative_volume": round(r.relative_volume, 2) if r.relative_volume == r.relative_volume else None,
                "trend_signal": r.trend_signal,
                "distance_from_resistance_pct": None,
                "resistance": None,
                "atr": None,
                "last_updated": r.timestamp.isoformat(),
                "is_alert": False,
                "model_available": r.model_available,
                "error": r.error,
            }
        )

    return ranked
