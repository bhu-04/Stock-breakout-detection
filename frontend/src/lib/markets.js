// Pure market-selection helpers (no React, no import.meta) so they can be unit-tested.
// No tickers live here: watchlists, defaults and examples all come from the backend.

export const FALLBACK_DEFAULT_MARKET = "IN";

// Used only if GET /api/markets fails, so the dropdown still works.
export const FALLBACK_MARKETS = Object.freeze([
  Object.freeze({ market: "IN", option_label: "India — NSE", label: "NSE · India" }),
  Object.freeze({ market: "US", option_label: "United States — US equities", label: "US Equities · United States" }),
]);

/** India unless the visitor previously chose something valid, or the server names another default. */
export function pickInitialMarket({ saved, serverDefault, markets }) {
  const codes = (markets && markets.length ? markets : FALLBACK_MARKETS).map((m) => m.market);
  if (saved && codes.includes(saved)) return saved;
  if (serverDefault && codes.includes(serverDefault)) return serverDefault;
  return codes.includes(FALLBACK_DEFAULT_MARKET) ? FALLBACK_DEFAULT_MARKET : codes[0];
}

/** A response may only be shown if it was produced for the market that is selected NOW. */
export function isForMarket(response, market) {
  return Boolean(response) && response.market === market;
}

/** Keep the chosen symbol if it is still listed, otherwise fall back to the first row. */
export function reconcileSelection(symbols, current) {
  return current && symbols.includes(current) ? current : symbols[0] ?? null;
}

export function marketOption(markets, code) {
  return (markets && markets.length ? markets : FALLBACK_MARKETS).find((m) => m.market === code) || null;
}

/** Drop one symbol from an /api/opportunities payload (optimistic update after a successful remove).
 *  The backend's next refresh replaces this, so only counts we can derive exactly are touched. */
export function withoutSymbol(opps, symbol) {
  const rows = opps.opportunities.filter((o) => o.symbol !== symbol);
  return {
    ...opps,
    opportunities: rows,
    symbols_unavailable: (opps.symbols_unavailable || []).filter((s) => s !== symbol),
    symbol_errors: Object.fromEntries(Object.entries(opps.symbol_errors || {}).filter(([s]) => s !== symbol)),
    watchlist: opps.watchlist ? { ...opps.watchlist, size: rows.length, customized: true } : opps.watchlist,
    summary: {
      ...opps.summary,
      stocks_monitored: rows.length,
      high_probability_opportunities: rows.filter((o) => o.is_alert).length,
      failed_symbols: Object.keys(opps.symbol_errors || {}).filter((s) => s !== symbol).length,
    },
  };
}
