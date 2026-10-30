"""Centralised market configuration: exchanges, symbol formats, currency,
time zone and regular-session hours.

Everything market-specific lives here so no other module has to hard-code
"$", "9:30", "America/New_York" or a ticker suffix. India (NSE) is the
default market; the US spec is kept so a US deployment stays possible, but
the two are never mixed implicitly: a symbol is always interpreted against
ONE selected market + exchange.

Session handling is deliberately conservative.
- India (NSE/BSE, 09:15-15:30 IST, Mon-Fri): we do NOT embed a holiday
  calendar - holidays are announced by exchange circular and change every
  year - so they are supplied through `MARKET_HOLIDAYS_IN` (ISO dates). A date
  that is not listed there is reported as "open per schedule", never as a
  confirmed trading day.
- US (NYSE/Nasdaq, 09:30-16:00 America/New_York, Mon-Fri): the full-day
  closures and 13:00 early closes follow fixed rules and are computed in
  `config/calendars.py`; ad-hoc closures go in `MARKET_HOLIDAYS_US`. The
  time zone is resolved through IANA data, so daylight saving is automatic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from backend.config.calendars import calendar_for


class InvalidSymbolError(ValueError):
    """Raised when a symbol cannot be interpreted for the selected market/exchange."""


@dataclass(frozen=True)
class MarketSpec:
    code: str                       # "IN" | "US"
    name: str                       # display name, e.g. "India"
    default_exchange: str
    exchange_suffixes: dict         # exchange -> provider suffix ("" = bare)
    timezone: str                   # IANA zone
    currency_code: str
    currency_symbol: str
    session_open: time
    session_close: time
    trading_days_per_year: int      # approximate; only used to annualise backtest Sharpe
    locale: str = "en-IN"
    base_pattern: re.Pattern = field(default=re.compile(r"^[A-Z0-9&_-]{1,20}$"))
    badge: str = "{exchange} · India"                    # header market indicator
    option: str = "India — {exchange}"                    # dropdown option text
    example_symbols: tuple = ()                               # input hints only - never a restriction

    def badge_label(self, exchange: Optional[str] = None) -> str:
        return self.badge.format(exchange=exchange or self.default_exchange)

    def option_label(self, exchange: Optional[str] = None) -> str:
        return self.option.format(exchange=exchange or self.default_exchange)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def session_minutes(self) -> int:
        o = self.session_open.hour * 60 + self.session_open.minute
        c = self.session_close.hour * 60 + self.session_close.minute
        return c - o

    def candles_per_day(self, interval_minutes: int) -> int:
        return max(1, self.session_minutes // max(1, interval_minutes))


INDIA = MarketSpec(
    code="IN",
    name="India",
    default_exchange="NSE",
    exchange_suffixes={"NSE": ".NS", "BSE": ".BO"},   # Yahoo Finance convention
    timezone="Asia/Kolkata",
    currency_code="INR",
    currency_symbol="\u20b9",
    session_open=time(9, 15),
    session_close=time(15, 30),
    trading_days_per_year=248,
    locale="en-IN",
    badge="{exchange} · India",
    option="India — {exchange}",
    example_symbols=("TATAMOTORS", "MARUTI", "BAJFINANCE", "WIPRO"),
)

US = MarketSpec(
    code="US",
    name="United States",
    default_exchange="US",
    exchange_suffixes={"US": ""},
    timezone="America/New_York",
    currency_code="USD",
    currency_symbol="$",
    session_open=time(9, 30),
    session_close=time(16, 0),
    trading_days_per_year=252,
    locale="en-US",
    base_pattern=re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$"),
    badge="US Equities · United States",
    option="United States — US equities",
    example_symbols=("NFLX", "ORCL", "COST", "INTC"),
)

MARKETS: dict[str, MarketSpec] = {INDIA.code: INDIA, US.code: US}
DEFAULT_MARKET = INDIA.code

# Bare tickers from the project's historical US default watchlist. Used ONLY
# to warn when a stale WATCHLIST env var is combined with the India market;
# never to decide which data to serve.
LEGACY_US_DEFAULT_WATCHLIST = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "JPM")

# Initial (not permanent) watchlists - the ONE place default tickers live. The
# frontend never hard-codes tickers; it reads them from the API. Each symbol
# must still be validated against the live provider - see README.
DEFAULT_INDIA_WATCHLIST = (
    "HDFCBANK", "RELIANCE", "LT", "INFY", "ITC", "ICICIBANK", "SBIN", "TCS", "BHARTIARTL", "HCLTECH",
)
DEFAULT_US_WATCHLIST = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "AVGO",
)


def get_market(code: str) -> MarketSpec:
    key = (code or "").strip().upper()
    if key not in MARKETS:
        raise ValueError(f"Unknown market {code!r}; supported: {sorted(MARKETS)}")
    return MARKETS[key]


def resolve_exchange(market: MarketSpec, exchange: Optional[str]) -> str:
    ex = (exchange or market.default_exchange).strip().upper()
    if ex not in market.exchange_suffixes:
        raise ValueError(
            f"Exchange {exchange!r} is not valid for market {market.code}; "
            f"supported: {sorted(market.exchange_suffixes)}"
        )
    return ex


def qualify_symbol(symbol: str, market: MarketSpec, exchange: Optional[str] = None) -> str:
    """Return the provider-format symbol for `symbol` in the selected market.

    India: bare `RELIANCE` -> `RELIANCE.NS` (or `.BO` when exchange=BSE). An
    already-suffixed `.NS`/`.BO` symbol is kept as written (explicit wins).
    Any other suffix (e.g. `.L`, `BRK.B`) is rejected - it is never silently
    reinterpreted as an Indian instrument.
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        raise InvalidSymbolError("empty symbol")

    ex = resolve_exchange(market, exchange)
    suffixes = {s.upper() for s in market.exchange_suffixes.values() if s}

    if market.code == "US":
        if not market.base_pattern.match(raw):
            raise InvalidSymbolError(f"{raw!r} is not a valid US ticker")
        # Share classes use Yahoo's dash form (BRK.B -> BRK-B). Never an exchange suffix.
        return raw.replace(".", "-")

    for suf in suffixes:
        if raw.endswith(suf):
            base = raw[: -len(suf)]
            if not market.base_pattern.match(base):
                raise InvalidSymbolError(f"{raw!r} is not a valid {market.name} symbol")
            return raw

    if "." in raw:
        raise InvalidSymbolError(
            f"{raw!r} has a suffix that does not belong to {market.name} "
            f"({', '.join(sorted(suffixes))}); refusing to guess"
        )
    if not market.base_pattern.match(raw):
        raise InvalidSymbolError(f"{raw!r} is not a valid {market.name} symbol")
    return raw + market.exchange_suffixes[ex]


def parse_watchlist(raw: str, market: MarketSpec, exchange: Optional[str] = None) -> tuple[list[str], list[dict]]:
    """Split a comma-separated watchlist into (valid provider symbols, rejected entries).

    Order is preserved and duplicates (after qualification) are dropped.
    """
    valid: list[str] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            q = qualify_symbol(item, market, exchange)
        except InvalidSymbolError as exc:
            rejected.append({"symbol": item.upper(), "reason": str(exc)})
            continue
        if q not in seen:
            seen.add(q)
            valid.append(q)
    return valid, rejected


def parse_holidays(raw: str) -> set[date]:
    out: set[date] = set()
    for item in (raw or "").split(","):
        item = item.strip()
        if item:
            out.add(date.fromisoformat(item))
    return out


def _non_trading_reason(market: MarketSpec, day: date, extra: set) -> Optional[str]:
    """'weekend' / 'holiday' when `day` is not a regular trading day, else None.

    Holidays = the market's computed calendar (US) plus any configured dates."""
    if day.weekday() >= 5:
        return "weekend"
    computed, _early = calendar_for(market.code, day)
    if day in extra or day in computed:
        return "holiday"
    return None


def session_status(
    market: MarketSpec, now: Optional[datetime] = None, holidays: Iterable[date] = ()
) -> dict:
    """Regular-session state for `market` at `now` (default: current time).

    `state` is "open" or "closed". `reason` explains it. The decision is made
    in the EXCHANGE's local time (never the server's), so US daylight-saving
    changes are handled by the IANA zone data.

    "open" means "inside regular hours on a weekday that is not a known
    holiday". For the US the holiday/early-close rules are computed; for
    India only configured holidays are known, so "open" there is NOT a
    confirmation that the exchange is actually trading (an unlisted holiday or
    ad-hoc closure would still read "open") - see `holiday_calendar_configured`.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")
    local = now.astimezone(market.tz)
    extra = set(holidays)

    _computed, early = calendar_for(market.code, local.date())
    close = early.get(local.date(), market.session_close)
    non_trading = _non_trading_reason(market, local.date(), extra)

    if non_trading:
        state, reason = "closed", non_trading
    elif local.time() < market.session_open:
        state, reason = "closed", "before_open"
    elif local.time() >= close:
        state, reason = "closed", "after_close"
    else:
        state, reason = "open", "in_session"

    return {
        "state": state,
        "reason": reason,
        "local_time": local.isoformat(),
        "timezone": market.timezone,
        "session_open": market.session_open.strftime("%H:%M"),
        "session_close": close.strftime("%H:%M"),
        "early_close": close != market.session_close,
        "holiday_calendar_configured": market.code == "US" or bool(extra),
        "next_open": _next_open(market, local, extra).isoformat() if state == "closed" else None,
    }


def _next_open(market: MarketSpec, local: datetime, extra: set) -> datetime:
    day = local.date()
    if not (_non_trading_reason(market, day, extra) is None and local.time() < market.session_open):
        day = day + timedelta(days=1)
    while _non_trading_reason(market, day, extra):
        day += timedelta(days=1)
    return datetime.combine(day, market.session_open, tzinfo=market.tz)
