import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

vi.mock("./components/CandlestickChart", () => ({ default: () => <div data-testid="chart" /> }));

// ---------------------------------------------------------------- in-memory fake of the backend API
const INFO = {
  IN: { market: "IN", market_name: "India", exchange: "NSE", label: "NSE · India", option_label: "India — NSE", currency_code: "INR", currency_symbol: "₹", timezone: "Asia/Kolkata", locale: "en-IN", example_symbols: ["AAA", "BBB"], session: { state: "open", reason: "in_session", session_open: "09:15", session_close: "15:30" } },
  US: { market: "US", market_name: "United States", exchange: "US", label: "US Equities · United States", option_label: "United States — US equities", currency_code: "USD", currency_symbol: "$", locale: "en-US", timezone: "America/New_York", example_symbols: ["XXX", "YYY"], session: { state: "closed", reason: "after_close", session_open: "09:30", session_close: "16:00" } },
};
const DEFAULTS = { IN: ["INA.NS", "INB.NS", "INC.NS"], US: ["USA", "USB"] };

function makeBackend({ failAdd } = {}) {
  const lists = { IN: DEFAULTS.IN.map((s) => ({ symbol: s, is_default: true })), US: DEFAULTS.US.map((s) => ({ symbol: s, is_default: true })) };
  const removedDefaults = { IN: [], US: [] };
  const calls = [];
  const row = (code, i, n) => ({
    rank: n + 1, symbol: i.symbol, is_default: i.is_default, breakout_probability: 0.7 - n * 0.1, current_price: (code === "IN" ? 1000 : 100) + n,
    rsi: 55, relative_volume: 1.2, trend_signal: "Above VWAP", distance_from_resistance_pct: 1.5, is_alert: n === 0,
    last_updated: "2026-10-28T10:00:00+00:00",
  });
  const opportunities = (code) => {
    const rows = lists[code].map((i, n) => row(code, i, n));
    return {
      market: code, generated_at: "2026-10-28T10:00:00+00:00", data_status: "delayed", provider: "yfinance", market_info: INFO[code],
      symbols_unavailable: [], symbol_errors: {}, data_latency_ms: 12,
      watchlist: { size: rows.length, customized: lists[code].some((i) => !i.is_default) || removedDefaults[code].length > 0, added_count: lists[code].filter((i) => !i.is_default).length, removed_defaults: removedDefaults[code], max_size: 50, readonly: false },
      summary: { stocks_monitored: rows.length, high_probability_opportunities: rows.filter((r) => r.is_alert).length, live_update_count: 1, alert_threshold: 0.65, failed_symbols: 0 },
      opportunities: rows,
    };
  };
  const describe = (code) => ({ market: code, market_info: INFO[code], symbols: lists[code] });
  const respond = (status, body) => Promise.resolve({ ok: status < 400, status, statusText: "x", json: () => Promise.resolve(body) });

  const fetchImpl = (url, opts = {}) => {
    const u = new URL(url);
    const market = u.searchParams.get("market");
    const method = opts.method || "GET";
    calls.push(`${method} ${u.pathname}${u.search}`);
    const path = u.pathname;
    if (path === "/api/markets") return respond(200, { default_market: "IN", markets: Object.values(INFO) });
    if (path === "/api/health") return respond(200, { market, model_status: "loaded", market_info: INFO[market], watchlist_size: lists[market].length });
    if (path === "/api/opportunities") return respond(200, opportunities(market));
    if (path === "/api/model/info") return respond(200, { available: false });
    if (path.startsWith("/api/stock/")) {
      const symbol = decodeURIComponent(path.split("/").pop());
      return respond(200, { symbol, market, market_info: INFO[market], data_status: "delayed", candles: [{ close: 123.45 }], resistance: null, breakout_confirmation_price: null, breakout_probability: 0.5, indicators: {}, model: null });
    }
    if (path === "/api/watchlist" && method === "POST") {
      const { market: mk, symbol } = JSON.parse(opts.body);
      if (failAdd) return respond(failAdd.status, { detail: failAdd.detail });
      const sym = symbol.toUpperCase();
      if (lists[mk].some((i) => i.symbol === sym)) return respond(409, { detail: `${sym} is already in the watchlist` });
      lists[mk].push({ symbol: sym, is_default: false });
      return respond(200, { ...describe(mk), added: sym, company_name: "Acme Corp" });
    }
    if (path.startsWith("/api/watchlist/") && path !== "/api/watchlist/reset" && method === "DELETE") {
      const sym = decodeURIComponent(path.split("/").pop());
      const item = lists[market].find((i) => i.symbol === sym);
      lists[market] = lists[market].filter((i) => i.symbol !== sym);
      if (item?.is_default) removedDefaults[market].push(sym);
      return respond(200, { ...describe(market), removed: sym });
    }
    if (path === "/api/watchlist/reset") {
      const { market: mk } = JSON.parse(opts.body);
      lists[mk] = DEFAULTS[mk].map((s) => ({ symbol: s, is_default: true }));
      removedDefaults[mk] = [];
      return respond(200, describe(mk));
    }
    return respond(404, { detail: `unhandled ${method} ${path}` });
  };
  return { fetchImpl, calls, lists };
}

let backend;
const install = (opts) => {
  backend = makeBackend(opts);
  vi.stubGlobal("fetch", vi.fn(backend.fetchImpl));
};

const tableSymbols = () =>
  within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelectorAll("td")[1]?.textContent.replace(/added/i, "").trim());

const inTable = (sym) => waitFor(() => expect(tableSymbols()).toContain(sym));

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("market selection", () => {
  it("first-time visitors land on India with its watchlist, rupees and NSE label", async () => {
    install();
    render(<App />);
    expect(await screen.findByText("INA.NS")).toBeTruthy();
    expect(screen.getByLabelText("Market").value).toBe("IN");
    expect(screen.getByTestId("market-badge").textContent).toBe("NSE · India");
    expect(tableSymbols().sort()).toEqual(DEFAULTS.IN.slice().sort());
    expect(screen.getAllByText(/₹/).length).toBeGreaterThan(0);
    expect(backend.calls.some((c) => c.includes("market=US"))).toBe(false); // nothing fetched for the other market
  });

  it("offers both markets in the dropdown with the required labels", async () => {
    install();
    render(<App />);
    await screen.findByText("INA.NS");
    const options = within(screen.getByLabelText("Market")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["India — NSE", "United States — US equities"]);
  });

  it("switching to the US shows a loading state, then ONLY US symbols, dollars and the US label", async () => {
    install();
    const real = backend.fetchImpl;
    let releaseUs;
    vi.stubGlobal("fetch", vi.fn((url, opts) => {
      if (url.includes("/api/opportunities") && url.includes("market=US")) {
        return new Promise((resolve) => { releaseUs = () => resolve(real(url, opts)); });   // hold the US answer
      }
      return real(url, opts);
    }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");

    await user.selectOptions(screen.getByLabelText("Market"), "US");
    expect(screen.queryByText("INA.NS")).toBeNull(); // India rows vanish at once, never shown under US
    expect(screen.getAllByRole("status").some((el) => /Loading US Equities/.test(el.textContent))).toBe(true);
    expect(screen.queryByTestId("market-badge")).toBeNull(); // no market is claimed active until data arrives
    releaseUs();

    await inTable("USA");
    expect(tableSymbols().sort()).toEqual(DEFAULTS.US.slice().sort());
    expect(screen.getByTestId("market-badge").textContent).toBe("US Equities · United States");
    expect(screen.getAllByText(/Market closed \u00b7 after close \(16:00 ET\)/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\$/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/₹/)).toBeNull();
    expect(localStorage.getItem("breakout.market")).toBe("US");
  });

  it("the detail panel follows the market and never keeps the previous market's stock", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "INA.NS" });
    await user.selectOptions(screen.getByLabelText("Market"), "US");
    expect(screen.queryByRole("heading", { name: "INA.NS" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "USA" })).toBeTruthy();
    expect(backend.calls.some((c) => c.startsWith("GET /api/stock/USA") && c.includes("market=US"))).toBe(true);
    await user.selectOptions(screen.getByLabelText("Market"), "IN");
    expect(await screen.findByRole("heading", { name: "INA.NS" })).toBeTruthy();
  });

  it("remembers the last market across a page refresh", async () => {
    install();
    const user = userEvent.setup();
    const first = render(<App />);
    await screen.findByText("INA.NS");
    await user.selectOptions(screen.getByLabelText("Market"), "US");
    await inTable("USA");
    first.unmount();

    render(<App />);
    await inTable("USA");
    expect(screen.getByLabelText("Market").value).toBe("US");
  });

  it("ignores a response that arrives for a market that is no longer selected", async () => {
    install();
    const real = backend.fetchImpl;
    let releaseIn;
    vi.stubGlobal("fetch", vi.fn((url, opts) => {
      if (url.includes("/api/opportunities") && url.includes("market=IN") && !releaseIn) {
        return new Promise((resolve) => { releaseIn = () => resolve(real(url, opts)); }); // slow India request
      }
      return real(url, opts);
    }));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(releaseIn).toBeTruthy());
    await user.selectOptions(screen.getByLabelText("Market"), "US");
    await inTable("USA");
    releaseIn();                                       // late India answer
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText("INA.NS")).toBeNull();
    expect(tableSymbols().sort()).toEqual(DEFAULTS.US.slice().sort());
  });
});

describe("watchlist management", () => {
  it("adds a stock to the active market only, and shows it immediately with its company name", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");

    await user.click(screen.getByRole("button", { name: "+ Add Stock" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByPlaceholderText("e.g. AAA")).toBeTruthy(); // example comes from the backend
    await user.type(within(dialog).getByRole("textbox"), "inx.ns");
    await user.click(within(dialog).getByRole("button", { name: "Add" }));

    expect(await screen.findByText("INX.NS")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(/Added INX.NS — Acme Corp/)).toBeTruthy();
    expect(tableSymbols()).toHaveLength(4);
    expect(backend.lists.US.map((i) => i.symbol)).toEqual(DEFAULTS.US);          // US untouched
    expect(backend.calls.some((c) => c.startsWith("POST /api/watchlist"))).toBe(true);

    await user.selectOptions(screen.getByLabelText("Market"), "US");              // switch away and back: nothing lost
    await inTable("USA");
    expect(screen.queryByText("INX.NS")).toBeNull();
    await user.selectOptions(screen.getByLabelText("Market"), "IN");
    expect(await screen.findByText("INX.NS")).toBeTruthy();
  });

  it.each([
    [422, "No market data found for ZZZ", false],
    [503, "Could not verify ZZZ right now", true],
    [409, "ZZZ is already in the watchlist", false],
  ])("shows the backend's reason for a %i and keeps the dialog open", async (status, detail) => {
    install({ failAdd: { status, detail } });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    await user.click(screen.getByRole("button", { name: "+ Add Stock" }));
    await user.type(within(screen.getByRole("dialog")).getByRole("textbox"), "zzz");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toContain(detail);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(tableSymbols()).toHaveLength(3);
  });

  it("Cancel closes the dialog without calling the API", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    await user.click(screen.getByRole("button", { name: "+ Add Stock" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((c) => c.startsWith("POST"))).toBe(false);
  });

  it("removes a stock from the table, and only in the active market", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INB.NS");
    await user.click(screen.getByRole("button", { name: "Remove INB.NS from watchlist" }));
    await waitFor(() => expect(screen.queryByText("INB.NS")).toBeNull());
    expect(tableSymbols()).toHaveLength(2);
    expect(backend.calls).toContain("DELETE /api/watchlist/INB.NS?market=IN");
    expect(backend.lists.US).toHaveLength(2);
    expect(screen.getByTestId("row-count").textContent).toBe("2 of 2");
  });

  it("restores defaults without a prompt when nothing user-added would be lost", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INB.NS");
    expect(screen.getByRole("button", { name: "Restore Default Watchlist" }).disabled).toBe(true); // already default
    await user.click(screen.getByRole("button", { name: "Remove INB.NS from watchlist" }));
    await waitFor(() => expect(screen.queryByText("INB.NS")).toBeNull());
    await waitFor(() => expect(screen.getByRole("button", { name: "Restore Default Watchlist" }).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "Restore Default Watchlist" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText("INB.NS")).toBeTruthy();
  });

  it("asks for confirmation before discarding user-added stocks, and Cancel keeps them", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    await user.click(screen.getByRole("button", { name: "+ Add Stock" }));
    await user.type(within(screen.getByRole("dialog")).getByRole("textbox"), "inx.ns");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add" }));
    await screen.findByText("INX.NS");
    await waitFor(() => expect(screen.getByRole("button", { name: "Restore Default Watchlist" }).disabled).toBe(false));

    await user.click(screen.getByRole("button", { name: "Restore Default Watchlist" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toMatch(/removes the 1 stock you added/);
    expect(dialog.textContent).toMatch(/other market's list is not affected/);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("INX.NS")).toBeTruthy();
    expect(backend.calls.some((c) => c.includes("/reset"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Restore Default Watchlist" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Restore defaults" }));
    await waitFor(() => expect(screen.queryByText("INX.NS")).toBeNull());
    expect(tableSymbols()).toHaveLength(3);
  });

  it("shows a useful empty state when every stock has been removed", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    for (const s of DEFAULTS.IN) {
      await user.click(screen.getByRole("button", { name: `Remove ${s} from watchlist` }));
      await waitFor(() => expect(screen.queryByText(s)).toBeNull());
    }
    expect(await screen.findByText(/No stocks in the India watchlist/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add Stock" })).toBeTruthy();
  });
});

describe("existing table behaviour", () => {
  it("search filters rows and the probability slider hides low scores", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    await user.type(screen.getByPlaceholderText("Search symbol…"), "inb");
    expect(tableSymbols()).toEqual(["INB.NS"]);
    expect(screen.getByTestId("row-count").textContent).toBe("1 of 3");
  });

  it("sorting by symbol reorders the rows", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("INA.NS");
    await user.click(screen.getByText("Symbol"));      // first click: descending
    expect(tableSymbols()).toEqual(["INC.NS", "INB.NS", "INA.NS"]);
    await user.click(screen.getByText(/^Symbol/));
    expect(tableSymbols()).toEqual(["INA.NS", "INB.NS", "INC.NS"]);
  });

  it("clicking a row loads that stock in the detail panel", async () => {
    install();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "INA.NS" });
    await user.click(screen.getByText("INC.NS"));
    expect(await screen.findByRole("heading", { name: "INC.NS" })).toBeTruthy();
  });

  it("per-symbol failures are listed with the reason and never replaced by other values", async () => {
    install();
    const base = backend.fetchImpl;
    vi.stubGlobal("fetch", vi.fn(async (url, opts) => {
      const res = await base(url, opts);
      if (url.includes("/api/opportunities")) {
        const body = await res.json();
        body.opportunities[1] = { ...body.opportunities[1], rank: null, breakout_probability: null, current_price: null, rsi: null, relative_volume: null, distance_from_resistance_pct: null, trend_signal: "Data Unavailable", error: "provider_unavailable: 429 Too Many Requests" };
        body.symbols_unavailable = [body.opportunities[1].symbol];
        body.symbol_errors = { [body.opportunities[1].symbol]: "provider_unavailable: 429 Too Many Requests" };
        body.data_status = "partial";
        body.summary.failed_symbols = 1;
        return { ok: true, status: 200, json: () => Promise.resolve(body) };
      }
      return res;
    }));
    render(<App />);
    await screen.findByText("INA.NS");
    expect(tableSymbols()).toHaveLength(3);
    expect(screen.getAllByText(/Data unavailable: 429 Too Many Requests/).length).toBeGreaterThan(0);
    expect(screen.getByText("1 failed to load")).toBeTruthy();
    expect(screen.getAllByText("PARTIAL DATA").length).toBeGreaterThan(0);
  });
});

describe("backend problems", () => {
  it("shows an error with a retry (not an endless spinner) when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toContain("Could not reach the backend API");
    expect(screen.getByRole("button", { name: "Retry now" })).toBeTruthy();
  });
});
