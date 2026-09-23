const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse failure
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),
  opportunities: () => request("/api/opportunities"),
  stockDetail: (symbol, limit = 200) => request(`/api/stock/${symbol}?limit=${limit}`),
  modelInfo: () => request("/api/model/info"),
  models: () => request("/api/models"),
  backtest: (threshold) => request(`/api/backtest${threshold ? `?threshold=${threshold}` : ""}`),
  config: () => request("/api/config"),
  train: (model) => request(`/api/train?model=${model}`, { method: "POST" }),
};
