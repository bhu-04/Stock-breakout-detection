"""Persistent, per-market watchlists.

Storage model: only the user's *changes* to each market's built-in default
list are saved, never a copy of the defaults:

    {"version": 1, "markets": {"IN": {"added": [...], "removed": [...]},
                               "US": {"added": [...], "removed": [...]}}}

    effective watchlist = (defaults - removed) + added

so (a) the original defaults are always available to restore, (b) a market
that was never touched simply follows the defaults (including any future
change to them), and (c) the two markets can never leak into each other -
each has its own entry and symbols are qualified for their own market.

The file is a small JSON document: no database dependency for a handful of
tickers. It is re-read on every call (cheap) so several worker processes see
each other's writes; writes are atomic (temp file + rename). Point
WATCHLIST_STORE_PATH at a persistent disk in production - on hosts with an
ephemeral filesystem the file is lost on redeploy and lists revert to the
defaults. A corrupt file is moved aside and the defaults are used; it is
never silently overwritten.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from backend.config.market import MARKETS

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / "user_data" / "watchlists.json"
_LOCK = threading.RLock()                 # one lock per process; the file is the cross-process source of truth


class WatchlistError(Exception):
    """Base class; `status_code` is the HTTP status the API maps it to."""

    status_code = 400


class DuplicateSymbolError(WatchlistError):
    status_code = 409


class SymbolNotInWatchlistError(WatchlistError):
    status_code = 404


class WatchlistFullError(WatchlistError):
    status_code = 422


class WatchlistStore:
    def __init__(self, path: Path | str, defaults: Callable[[str], list[str]], max_size: int = 50) -> None:
        self.path = Path(path)
        self._defaults = defaults
        self.max_size = max_size

    # ------------------------------------------------------------ persistence
    def _read(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "markets": {}}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("markets", {}), dict):
                raise ValueError("unexpected structure")
            return data
        except ValueError as exc:
            backup = self.path.with_suffix(f".corrupt-{os.getpid()}.json")
            try:
                self.path.replace(backup)
            except OSError:  # pragma: no cover - best effort
                backup = None
            logger.error("Watchlist file %s is unreadable (%s); using defaults%s", self.path, exc,
                         f", original kept as {backup}" if backup else "")
            return {"version": 1, "markets": {}}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _check_market(market: str) -> str:
        code = (market or "").strip().upper()
        if code not in MARKETS:
            raise WatchlistError(f"Unknown market {market!r}; supported: {sorted(MARKETS)}")
        return code

    def _entry(self, data: dict, code: str) -> dict:
        raw = data.get("markets", {}).get(code, {})
        defaults = self._defaults(code)
        added = [s for s in raw.get("added", []) if isinstance(s, str) and s not in defaults]
        removed = [s for s in raw.get("removed", []) if isinstance(s, str) and s in defaults]
        return {"added": list(dict.fromkeys(added)), "removed": list(dict.fromkeys(removed))}

    def _save_entry(self, data: dict, code: str, entry: dict) -> None:
        data.setdefault("markets", {})
        if entry["added"] or entry["removed"]:
            data["markets"][code] = entry
        else:
            data["markets"].pop(code, None)           # back to pristine defaults
        self._write(data)

    # ------------------------------------------------------------ reads
    def symbols(self, market: str) -> list[str]:
        return [item["symbol"] for item in self.items(market)]

    def items(self, market: str) -> list[dict]:
        code = self._check_market(market)
        with _LOCK:
            entry = self._entry(self._read(), code)
        defaults = self._defaults(code)
        out = [{"symbol": s, "is_default": True} for s in defaults if s not in entry["removed"]]
        out += [{"symbol": s, "is_default": False} for s in entry["added"]]
        return out

    def describe(self, market: str) -> dict:
        code = self._check_market(market)
        with _LOCK:
            entry = self._entry(self._read(), code)
        defaults = self._defaults(code)
        return {
            "market": code,
            "symbols": self.items(code),
            "defaults": defaults,
            "removed_defaults": entry["removed"],
            "customized": bool(entry["added"] or entry["removed"]),
            "max_size": self.max_size,
        }

    # ------------------------------------------------------------ writes
    def add(self, market: str, symbol: str) -> dict:
        """`symbol` must already be qualified/validated for `market` by the caller."""
        code = self._check_market(market)
        with _LOCK:
            data = self._read()
            entry = self._entry(data, code)
            defaults = self._defaults(code)
            current = [s for s in defaults if s not in entry["removed"]] + entry["added"]
            if symbol in current:
                raise DuplicateSymbolError(f"{symbol} is already in the {code} watchlist")
            if len(current) >= self.max_size:
                raise WatchlistFullError(f"The {code} watchlist is limited to {self.max_size} symbols")
            if symbol in defaults:                     # re-adding a removed default restores it
                entry["removed"].remove(symbol)
            else:
                entry["added"].append(symbol)
            self._save_entry(data, code, entry)
        return self.describe(code)

    def remove(self, market: str, symbol: str) -> dict:
        code = self._check_market(market)
        with _LOCK:
            data = self._read()
            entry = self._entry(data, code)
            defaults = self._defaults(code)
            if symbol in entry["added"]:
                entry["added"].remove(symbol)
            elif symbol in defaults and symbol not in entry["removed"]:
                entry["removed"].append(symbol)
            else:
                raise SymbolNotInWatchlistError(f"{symbol} is not in the {code} watchlist")
            self._save_entry(data, code, entry)
        return self.describe(code)

    def reset(self, market: str) -> dict:
        code = self._check_market(market)
        with _LOCK:
            data = self._read()
            data.setdefault("markets", {}).pop(code, None)
            self._write(data)
        return self.describe(code)


_STORES: dict[str, WatchlistStore] = {}


def get_store() -> WatchlistStore:
    """Store for the current settings (cached per path, so tests can point at a temp file)."""
    from backend.config.settings import settings

    path = str(Path(settings.watchlist_store_path) if settings.watchlist_store_path else DEFAULT_STORE_PATH)
    store = _STORES.get(path)
    if store is None:
        store = _STORES[path] = WatchlistStore(path, settings.default_watchlist, settings.max_watchlist_size)
    store.max_size = settings.max_watchlist_size
    return store
