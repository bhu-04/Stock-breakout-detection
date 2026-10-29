import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import { resolveMarketInfo } from "./lib/format";
import Header from "./components/Header";
import SummaryCards from "./components/SummaryCards";
import OpportunityTable from "./components/OpportunityTable";
import StockDetail from "./components/StockDetail";
import ModelInfoPanel from "./components/ModelInfoPanel";
import SystemStatusPanel from "./components/SystemStatusPanel";

const REFRESH_MS = 15000;

export default function App() {
  const [opportunitiesData, setOpportunitiesData] = useState(null);
  const [health, setHealth] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [opps, h] = await Promise.all([api.opportunities(), api.health()]);
      setOpportunitiesData(opps);
      setHealth(h);
      setError(null);
      // Keep the selection only if it is still on the backend's current watchlist
      // (e.g. after a redeploy or market switch); otherwise fall back to the first row.
      const symbols = opps.opportunities.map((o) => o.symbol);
      setSelectedSymbol((current) => (current && symbols.includes(current) ? current : symbols[0] ?? null));
    } catch (e) {
      setError(e.message || "Failed to reach the backend API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    api
      .modelInfo()
      .then(setModelInfo)
      .catch(() => setModelInfo(null));
  }, [opportunitiesData?.summary?.live_update_count]);

  const marketInfo = resolveMarketInfo(opportunitiesData?.market_info || health?.market_info);
  const isEmpty = opportunitiesData && opportunitiesData.opportunities.length === 0;

  return (
    <div className="min-h-screen bg-base-950 text-ink-100">
      <Header
        health={health}
        lastUpdate={opportunitiesData?.generated_at}
        dataStatus={opportunitiesData?.data_status || health?.data_status}
        dataFeed={opportunitiesData?.data_feed || health?.data_feed}
        marketInfo={marketInfo}
      />

      <main className="mx-auto flex max-w-[1400px] flex-col gap-4 p-6">
        {error && (
          <div className="rounded border border-accent-700 bg-accent-900/30 px-4 py-3 text-sm text-accent-400">
            {error}. Retrying automatically every {REFRESH_MS / 1000}s.
          </div>
        )}

        {loading && !opportunitiesData && (
          <div className="rounded border border-base-800 bg-base-900 px-4 py-8 text-center text-sm text-ink-500">
            Loading market data…
          </div>
        )}

        {opportunitiesData && (
          <>
            <SummaryCards summary={opportunitiesData.summary} modelStatus={health?.model_status} />

            {isEmpty ? (
              <div className="rounded border border-base-800 bg-base-900 px-4 py-8 text-center text-sm text-ink-500">
                No breakout opportunities detected in the current watchlist.
              </div>
            ) : (
              <OpportunityTable
                opportunities={opportunitiesData.opportunities}
                onSelect={setSelectedSymbol}
                selectedSymbol={selectedSymbol}
                marketInfo={marketInfo}
              />
            )}

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
              <StockDetail symbol={selectedSymbol} marketInfo={marketInfo} />
              <div className="flex flex-col gap-4">
                <SystemStatusPanel
                  health={health}
                  error={error}
                  lastUpdate={opportunitiesData?.generated_at}
                  dataStatus={opportunitiesData?.data_status}
                  dataFeed={opportunitiesData?.data_feed}
                  latencyMs={opportunitiesData?.data_latency_ms}
                  symbolsUnavailable={opportunitiesData?.symbols_unavailable}
                  marketInfo={marketInfo}
                  provider={opportunitiesData?.provider || health?.market_data_provider}
                />
                <ModelInfoPanel modelInfo={modelInfo} />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}