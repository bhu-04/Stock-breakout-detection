const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/** Error carrying the HTTP status so the UI can tell "invalid" (422) from "provider down" (503). */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new ApiError(0, "Could not reach the backend API");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      // ignore parse failure
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/** `/path?market=US&limit=60` - the market is ALWAYS sent explicitly. */
export function withQuery(path, params = {}) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return q ? `${path}?${q}` : path;
}

const json = (method, body) => ({ method, body: JSON.stringify(body) });

export const api = {
  markets: () => request("/api/markets"),
  health: (market, signal) => request(withQuery("/api/health", { market }), { signal }),
  opportunities: (market, signal) => request(withQuery("/api/opportunities", { market }), { signal }),
  stockDetail: (symbol, market, limit = 200, signal) =>
    request(withQuery(`/api/stock/${encodeURIComponent(symbol)}`, { market, limit }), { signal }),
  watchlist: (market) => request(withQuery("/api/watchlist", { market })),
  addSymbol: (market, symbol) => request("/api/watchlist", json("POST", { market, symbol })),
  removeSymbol: (market, symbol) =>
    request(withQuery(`/api/watchlist/${encodeURIComponent(symbol)}`, { market }), { method: "DELETE" }),
  resetWatchlist: (market) => request("/api/watchlist/reset", json("POST", { market })),
  modelInfo: () => request("/api/model/info"),
  models: () => request("/api/models"),
  backtest: (threshold) => request(withQuery("/api/backtest", { threshold })),
  config: () => request("/api/config"),
  train: (model) => request(withQuery("/api/train", { model }), { method: "POST" }),
};
