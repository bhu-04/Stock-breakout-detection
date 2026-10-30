import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./lib/api";
import { resolveMarketInfo } from "./lib/format";
import { isForMarket, marketOption, pickInitialMarket, reconcileSelection, withoutSymbol } from "./lib/markets";
import { loadSavedMarket, saveMarket } from "./lib/prefs";
import Header from "./components/Header";
import SummaryCards from "./components/SummaryCards";
import OpportunityTable from "./components/OpportunityTable";
import StockDetail from "./components/StockDetail";
import ModelInfoPanel from "./components/ModelInfoPanel";
import SystemStatusPanel from "./components/SystemStatusPanel";
import AddStockDialog from "./components/AddStockDialog";
import ConfirmDialog from "./components/ConfirmDialog";

const REFRESH_MS = 15000;

function Panel({ children, role }) {
  return (
    <div role={role} className="rounded border border-base-800 bg-base-900 px-4 py-8 text-center text-sm text-ink-500">
      {children}
    </div>
  );
}

export default function App() {
  const [markets, setMarkets] = useState(null);
  const [market, setMarket] = useState(null); // the SELECTED market; null until /api/markets has answered
  // Last good payload, tagged with the market it was produced for. It is only ever displayed
  // while its tag equals the selected market, so one market's data can't appear under another.
  const [snapshot, setSnapshot] = useState(null);
  const [errorState, setErrorState] = useState(null); // { market, message }
  const [modelInfo, setModelInfo] = useState(null);
  const [selectedBy, setSelectedBy] = useState({}); // selected symbol, per market
  const [dialog, setDialog] = useState(null); // "add" | "restore" | null
  const [pending, setPending] = useState({ market: null, symbols: [] }); // just added, data still loading
  const [removing, setRemoving] = useState([]);
  const [restoring, setRestoring] = useState(false);
  const [notice, setNotice] = useState(null); // { kind: "ok" | "error", text }
  const refreshRef = useRef(null);

  // 1) Which markets exist, and which one to start on (saved choice -> server default -> India).
  useEffect(() => {
    let alive = true;
    const saved = loadSavedMarket();
    api
      .markets()
      .then((res) => {
        if (!alive) return;
        setMarkets(res.markets);
        setMarket(pickInitialMarket({ saved, serverDefault: res.default_market, markets: res.markets }));
      })
      .catch(() => {
        if (alive) setMarket(pickInitialMarket({ saved, serverDefault: null, markets: null }));
      });
    return () => {
      alive = false;
    };
  }, []);

  // 2) Poll ONLY the selected market. Changing market aborts the old requests and starts fresh.
  useEffect(() => {
    if (!market) return undefined;
    const ctrl = new AbortController();
    let seq = 0;
    let applied = 0;
    let active = 0;

    const run = async () => {
      const mine = ++seq;
      active += 1;
      try {
        const [opps, health] = await Promise.all([api.opportunities(market, ctrl.signal), api.health(market, ctrl.signal)]);
        if (ctrl.signal.aborted || mine < applied) return false;
        if (opps.market !== market || health.market !== market) {
          throw new Error(`Backend answered for market ${opps.market}, but ${market} was requested`);
        }
        applied = mine;
        setSnapshot({ market, opps, health });
        setErrorState(null);
        setPending((p) =>
          p.market === market ? { market, symbols: p.symbols.filter((s) => !opps.opportunities.some((o) => o.symbol === s)) } : p,
        );
        return true;
      } catch (e) {
        if (ctrl.signal.aborted || e?.name === "AbortError") return false;
        setErrorState({ market, message: e.message || "Failed to reach the backend API" });
        return false;
      } finally {
        active -= 1;
      }
    };
    refreshRef.current = run;

    run();
    const timer = setInterval(() => {
      if (!document.hidden && active === 0) run();
    }, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden && active === 0) run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      ctrl.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [market]);

  const modelStatus = snapshot?.health?.model_status;
  useEffect(() => {
    api
      .modelInfo()
      .then(setModelInfo)
      .catch(() => setModelInfo(null));
  }, [modelStatus]);

  useEffect(() => {
    if (!notice) return undefined;
    const id = setTimeout(() => setNotice(null), 7000);
    return () => clearTimeout(id);
  }, [notice]);

  // ---- what is on screen: only data that belongs to the selected market
  const current = isForMarket(snapshot, market) ? snapshot : null;
  const opps = current?.opps ?? null;
  const health = current?.health ?? null;
  const marketInfo = opps?.market_info || health?.market_info || null;
  const m = resolveMarketInfo(marketInfo);
  const error = errorState && errorState.market === market ? errorState.message : null;
  const switching = Boolean(market) && !current && !error;
  const symbols = opps ? opps.opportunities.map((o) => o.symbol) : [];
  const selectedSymbol = opps ? reconcileSelection(symbols, selectedBy[market]) : null;
  const pendingSymbols = pending.market === market ? pending.symbols : [];
  const marketLabel = marketOption(markets, market)?.label;

  const changeMarket = (code) => {
    if (code === market) return;
    saveMarket(code);
    setDialog(null);
    setNotice(null);
    setMarket(code);
  };

  const refreshNow = useCallback(async () => (refreshRef.current ? refreshRef.current() : false), []);

  const handleAdd = async (symbol) => {
    const target = market;
    const res = await api.addSymbol(target, symbol); // throws -> the dialog shows the reason
    setDialog(null);
    setPending((p) => ({ market: target, symbols: [...(p.market === target ? p.symbols : []), res.added] }));
    setNotice({ kind: "ok", text: `Added ${res.added}${res.company_name ? ` — ${res.company_name}` : ""} to the ${res.market_info?.label || target} watchlist.` });
    const ok = await refreshNow();
    if (ok) setPending((p) => (p.market === target ? { market: target, symbols: [] } : p));
  };

  const handleRemove = async (symbol) => {
    const target = market;
    setRemoving((r) => [...r, symbol]);
    try {
      await api.removeSymbol(target, symbol);
      setSnapshot((prev) => (prev && prev.market === target ? { ...prev, opps: withoutSymbol(prev.opps, symbol) } : prev));
      setNotice({ kind: "ok", text: `Removed ${symbol}.` });
      refreshNow();
    } catch (e) {
      setNotice({ kind: "error", text: `Could not remove ${symbol}: ${e.message}` });
    } finally {
      setRemoving((r) => r.filter((s) => s !== symbol));
    }
  };

  const doRestore = async () => {
    const target = market;
    setRestoring(true);
    try {
      await api.resetWatchlist(target);
      setDialog(null);
      setNotice({ kind: "ok", text: `Restored the default ${marketLabel || target} watchlist.` });
      await refreshNow();
    } catch (e) {
      setDialog(null);
      setNotice({ kind: "error", text: `Could not restore defaults: ${e.message}` });
    } finally {
      setRestoring(false);
    }
  };

  const requestRestore = () => {
    // Only user-added stocks would be discarded, so only that case needs a confirmation.
    if ((opps?.watchlist?.added_count || 0) > 0) setDialog("restore");
    else doRestore();
  };

  const wl = opps?.watchlist;
  const restoreMessage = wl
    ? `This removes the ${wl.added_count} stock${wl.added_count === 1 ? "" : "s"} you added` +
      (wl.removed_defaults?.length ? ` and brings back ${wl.removed_defaults.length} default${wl.removed_defaults.length === 1 ? "" : "s"} you removed` : "") +
      `. Only the ${m.market_name} watchlist changes; the other market's list is not affected.`
    : "";

  return (
    <div className="min-h-screen bg-base-950 text-ink-100">
      <Header
        markets={markets}
        market={market}
        onMarketChange={changeMarket}
        switching={switching}
        pendingLabel={marketLabel}
        marketInfo={marketInfo}
        symbolCount={opps?.summary?.stocks_monitored}
        lastUpdate={opps?.generated_at}
        dataStatus={opps?.data_status}
        dataFeed={opps?.data_feed}
      />

      <main className="mx-auto flex max-w-[1400px] flex-col gap-4 p-6">
        {error && (
          <div role="alert" className="rounded border border-accent-700 bg-accent-900/30 px-4 py-3 text-sm text-accent-400">
            {error}. Retrying automatically every {REFRESH_MS / 1000}s.
          </div>
        )}

        {notice && (
          <div
            role="status"
            className={`flex items-center justify-between rounded border px-4 py-2 text-xs ${
              notice.kind === "ok" ? "border-base-700 bg-base-900 text-ink-300" : "border-accent-700 bg-accent-900/30 text-accent-400"
            }`}
          >
            <span>{notice.text}</span>
            <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)} className="ml-4 text-ink-500 hover:text-ink-100">
              ×
            </button>
          </div>
        )}

        {switching && <Panel role="status">Loading {marketLabel || "market"} watchlist…</Panel>}

        {!current && error && (
          <Panel>
            <button type="button" onClick={() => refreshNow()} className="rounded border border-base-700 px-3 py-1.5 text-xs text-ink-300 hover:bg-base-800">
              Retry now
            </button>
          </Panel>
        )}

        {current && (
          <>
            <SummaryCards summary={opps.summary} modelStatus={health?.model_status} />

            <OpportunityTable
              key={market}
              opportunities={opps.opportunities}
              onSelect={(sym) => setSelectedBy((prev) => ({ ...prev, [market]: sym }))}
              selectedSymbol={selectedSymbol}
              marketInfo={marketInfo}
              watchlist={wl}
              pendingSymbols={pendingSymbols}
              removingSymbols={removing}
              onAdd={() => setDialog("add")}
              onRemove={handleRemove}
              onRestore={requestRestore}
            />

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
              <StockDetail key={market} symbol={selectedSymbol} market={market} />
              <div className="flex flex-col gap-4">
                <SystemStatusPanel
                  health={health}
                  error={error}
                  lastUpdate={opps.generated_at}
                  dataStatus={opps.data_status}
                  dataFeed={opps.data_feed}
                  latencyMs={opps.data_latency_ms}
                  symbolsUnavailable={opps.symbols_unavailable}
                  symbolErrors={opps.symbol_errors}
                  marketInfo={marketInfo}
                  provider={opps.provider || health?.market_data_provider}
                  watchlistSize={opps.summary?.stocks_monitored}
                />
                <ModelInfoPanel modelInfo={modelInfo} />
              </div>
            </div>
          </>
        )}
      </main>

      {dialog === "add" && <AddStockDialog marketInfo={marketInfo} onSubmit={handleAdd} onClose={() => setDialog(null)} />}
      {dialog === "restore" && (
        <ConfirmDialog
          title={`Restore default ${m.market_name} watchlist?`}
          message={restoreMessage}
          confirmLabel="Restore defaults"
          busy={restoring}
          onConfirm={doRestore}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
