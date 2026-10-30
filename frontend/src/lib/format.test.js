import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_MARKET_INFO, formatDateTime, formatPrice, formatTime, resolveMarketInfo, sessionLabel } from "./format.js";

test("default market info is India / INR / Asia/Kolkata, not US", () => {
  assert.equal(DEFAULT_MARKET_INFO.market, "IN");
  assert.equal(DEFAULT_MARKET_INFO.exchange, "NSE");
  assert.equal(DEFAULT_MARKET_INFO.currency_symbol, "\u20b9");
  assert.equal(DEFAULT_MARKET_INFO.timezone, "Asia/Kolkata");
});

test("formatPrice uses rupee symbol and Indian digit grouping, never $", () => {
  const out = formatPrice(1234567.5);
  assert.equal(out, "\u20b912,34,567.50");
  assert.ok(!out.includes("$"));
  assert.equal(formatPrice(2850.1, { currency_symbol: "\u20b9" }), "\u20b92,850.10");
});

test("formatPrice handles missing values", () => {
  assert.equal(formatPrice(null), "\u2014");
  assert.equal(formatPrice(undefined), "\u2014");
  assert.equal(formatPrice(NaN), "\u2014");
});

test("formatPrice honours a backend-supplied US market (US stays optional)", () => {
  const us = { currency_symbol: "$", locale: "en-US" };
  assert.equal(formatPrice(1234.5, us), "$1,234.50");
});

test("timestamps render in Asia/Kolkata regardless of the browser zone", () => {
  // 04:00 UTC == 09:30 IST
  assert.equal(formatTime("2026-10-29T04:00:00+00:00"), "09:30");
  assert.equal(formatTime("2026-10-29T04:00:00+00:00", { timezone: "Asia/Kolkata" }), "09:30");
  assert.match(formatDateTime("2026-10-29T04:00:00+00:00"), /09:30:00 IST$/);
  assert.equal(formatTime(null), "\u2014");
});

test("resolveMarketInfo overlays backend values on India defaults", () => {
  assert.equal(resolveMarketInfo({ exchange: "BSE" }).exchange, "BSE");
  assert.equal(resolveMarketInfo({ exchange: "BSE" }).currency_symbol, "\u20b9");
  assert.equal(resolveMarketInfo(null).market, "IN");
});

test("sessionLabel", () => {
  assert.equal(sessionLabel({ state: "open", reason: "in_session" }), "Market open");
  assert.equal(
    sessionLabel({ state: "closed", reason: "weekend", session_open: "09:15", session_close: "15:30" }),
    "Market closed \u00b7 weekend",
  );
  assert.equal(
    sessionLabel({ state: "closed", reason: "after_close", session_open: "09:15", session_close: "15:30" }),
    "Market closed \u00b7 after close (15:30 IST)",
  );
  assert.equal(sessionLabel(null), null);
});
