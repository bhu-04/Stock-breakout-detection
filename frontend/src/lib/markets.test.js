import test from "node:test";
import assert from "node:assert/strict";
import { FALLBACK_MARKETS, isForMarket, marketOption, pickInitialMarket, reconcileSelection, withoutSymbol } from "./markets.js";
import { loadSavedMarket, saveMarket } from "./prefs.js";
import { formatDateTime, formatPrice, sessionLabel } from "./format.js";

const memory = () => {
  const d = new Map();
  return { getItem: (k) => (d.has(k) ? d.get(k) : null), setItem: (k, v) => d.set(k, String(v)) };
};

test("a first-time visitor gets India", () => {
  assert.equal(pickInitialMarket({ saved: loadSavedMarket(memory()), serverDefault: "IN", markets: FALLBACK_MARKETS }), "IN");
  assert.equal(pickInitialMarket({ saved: null, serverDefault: null, markets: null }), "IN");
});

test("the last selected market is restored; junk values are ignored", () => {
  const store = memory();
  saveMarket("US", store);
  assert.equal(pickInitialMarket({ saved: loadSavedMarket(store), serverDefault: "IN", markets: FALLBACK_MARKETS }), "US");
  assert.equal(pickInitialMarket({ saved: "XX", serverDefault: "IN", markets: FALLBACK_MARKETS }), "IN");
});

test("broken browser storage never throws", () => {
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(loadSavedMarket(broken), null);
  assert.doesNotThrow(() => saveMarket("US", broken));
});

test("a response is only shown for the market it was produced for", () => {
  assert.equal(isForMarket({ market: "US" }, "US"), true);
  assert.equal(isForMarket({ market: "IN" }, "US"), false);
  assert.equal(isForMarket(null, "US"), false);
});

test("selection survives refreshes but never points at a symbol that is gone", () => {
  assert.equal(reconcileSelection(["A", "B"], "B"), "B");
  assert.equal(reconcileSelection(["A", "B"], "Z"), "A");
  assert.equal(reconcileSelection([], "Z"), null);
});

test("dropdown options carry the required labels", () => {
  assert.equal(marketOption(null, "IN").option_label, "India — NSE");
  assert.equal(marketOption(null, "US").option_label, "United States — US equities");
});

test("withoutSymbol recomputes counts from the remaining rows", () => {
  const opps = {
    opportunities: [{ symbol: "A", is_alert: true }, { symbol: "B", is_alert: false }, { symbol: "C", is_alert: true }],
    symbols_unavailable: ["B"],
    symbol_errors: { B: "x" },
    watchlist: { size: 3, customized: false },
    summary: { stocks_monitored: 3, high_probability_opportunities: 2, failed_symbols: 1 },
  };
  const out = withoutSymbol(opps, "A");
  assert.deepEqual(out.opportunities.map((o) => o.symbol), ["B", "C"]);
  assert.equal(out.summary.stocks_monitored, 2);
  assert.equal(out.summary.high_probability_opportunities, 1);
  assert.equal(out.watchlist.customized, true);
  assert.equal(withoutSymbol(opps, "B").summary.failed_symbols, 0);
});

test("US formatting: dollars and New York time, with early-close wording", () => {
  const us = { market: "US", currency_symbol: "$", locale: "en-US", timezone: "America/New_York" };
  assert.equal(formatPrice(1234.5, us), "$1,234.50");
  assert.match(formatDateTime("2026-10-29T14:00:00+00:00", us), /10:00:00 ET$/); // EDT, UTC-4
  assert.equal(
    sessionLabel({ state: "open", early_close: true, session_close: "13:00" }, us),
    "Market open · early close 13:00 ET",
  );
});
