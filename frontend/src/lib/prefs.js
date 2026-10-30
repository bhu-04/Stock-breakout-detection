// The ONLY place the app touches browser storage: it remembers which market was last
// selected (a per-browser convenience). Watchlists are NOT stored here - they live on the
// backend, so they are the same in every browser and survive redeploys of the frontend.
// Every access is wrapped: storage can be unavailable (private mode, blocked cookies).

const KEY = "breakout.market";

export function loadSavedMarket(storage = globalThis.localStorage) {
  try {
    return storage?.getItem(KEY) || null;
  } catch {
    return null;
  }
}

export function saveMarket(code, storage = globalThis.localStorage) {
  try {
    storage?.setItem(KEY, code);
  } catch {
    // ignore: the selection simply won't be remembered
  }
}
