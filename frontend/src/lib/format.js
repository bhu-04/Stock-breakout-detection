// Market-aware formatting helpers. Pure functions (no React, no import.meta)
// so they can be unit-tested with `node --test`.
//
// Defaults are India (INR, Asia/Kolkata). The backend sends the real values in
// `market_info` on every response; these constants are only a last-resort
// fallback for the moment before the first response arrives and must never be
// a US default.

export const DEFAULT_MARKET_INFO = Object.freeze({
  market: "IN",
  market_name: "India",
  exchange: "NSE",
  currency_code: "INR",
  currency_symbol: "\u20b9",
  timezone: "Asia/Kolkata",
  locale: "en-IN",
});

const TZ_LABEL = { "Asia/Kolkata": "IST", "America/New_York": "ET" };

export function resolveMarketInfo(info) {
  return { ...DEFAULT_MARKET_INFO, ...(info || {}) };
}

export function timeZoneLabel(timeZone) {
  return TZ_LABEL[timeZone] || timeZone;
}

export function formatPrice(value, info) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2014";
  const m = resolveMarketInfo(info);
  const num = new Intl.NumberFormat(m.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
  return `${m.currency_symbol}${num}`;
}

export function formatTime(ts, info) {
  if (!ts) return "\u2014";
  const m = resolveMarketInfo(info);
  return new Date(ts).toLocaleTimeString(m.locale, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: m.timezone });
}

export function formatDateTime(ts, info) {
  if (!ts) return "\u2014";
  const m = resolveMarketInfo(info);
  return new Date(ts).toLocaleString(m.locale, { hour12: false, timeZone: m.timezone }) + ` ${timeZoneLabel(m.timezone)}`;
}

export function sessionLabel(session, info) {
  if (!session) return null;
  const m = resolveMarketInfo(info);
  if (session.state === "open") return "Market open";
  const reason = {
    before_open: `before open (${session.session_open} ${timeZoneLabel(m.timezone)})`,
    after_close: `after close (${session.session_close} ${timeZoneLabel(m.timezone)})`,
    weekend: "weekend",
    holiday: "holiday",
  }[session.reason] || session.reason;
  return `Market closed \u00b7 ${reason}`;
}
