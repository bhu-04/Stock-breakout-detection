import { formatDateTime, resolveMarketInfo, sessionLabel } from "../lib/format";

function StatusRow({ label, ok, okLabel, badLabel }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-xs">
      <span className="text-ink-500">{label}</span>
      <span className={`flex items-center gap-1.5 font-medium ${ok ? "text-up" : "text-accent-400"}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-up" : "bg-accent-400"}`} />
        {ok ? okLabel : badLabel}
      </span>
    </div>
  );
}

const DATA_STATUS_LABEL = {
  live: "Live",
  delayed: "Delayed",
  demo: "Demo / Simulated",
  partial: "Partial (some symbols unavailable)",
  unavailable: "Unavailable",
};

export default function SystemStatusPanel({
  health,
  error,
  lastUpdate,
  staleAfterMs = 60000,
  dataStatus,
  dataFeed,
  latencyMs,
  symbolsUnavailable,
  symbolErrors,
  marketInfo,
  provider,
  watchlistSize,
}) {
  const m = resolveMarketInfo(marketInfo);
  const session = sessionLabel(m.session, m);
  const isStale = lastUpdate ? Date.now() - new Date(lastUpdate).getTime() > staleAfterMs : false;
  const status = dataStatus || health?.data_status || "demo";

  return (
    <div className="rounded border border-base-800 bg-base-900 p-4">
      <div className="mb-2 text-[11px] uppercase tracking-wide text-ink-500">System Status</div>
      <StatusRow label="Backend API" ok={!error} okLabel="Reachable" badLabel="Unreachable" />
      <div className="flex items-center justify-between py-1.5 text-xs">
        <span className="text-ink-500">Market</span>
        <span className="font-mono text-ink-300">{m.exchange} · {m.market_name} · {m.currency_code}</span>
      </div>
      {session && (
        <div className="flex items-center justify-between py-1.5 text-xs">
          <span className="text-ink-500">Session</span>
          <span className={`font-medium ${m.session?.state === "open" ? "text-up" : "text-ink-300"}`}>{session}</span>
        </div>
      )}
      {provider && (
        <div className="flex items-center justify-between py-1.5 text-xs">
          <span className="text-ink-500">Provider</span>
          <span className="font-mono text-ink-300">{provider}</span>
        </div>
      )}
      <div className="flex items-center justify-between py-1.5 text-xs">
        <span className="text-ink-500">Data status</span>
        <span
          className={`font-medium ${status === "live" ? "text-up" : status === "unavailable" ? "text-red-500" : "text-accent-400"}`}
        >
          {DATA_STATUS_LABEL[status] || status}{dataFeed && status === "live" ? ` (${dataFeed.toUpperCase()})` : ""}
        </span>
      </div>
      {latencyMs != null && (
        <div className="flex items-center justify-between py-1.5 text-xs">
          <span className="text-ink-500">Data latency</span>
          <span className="font-mono text-ink-300">{latencyMs} ms</span>
        </div>
      )}
      {health?.config_warnings?.length > 0 && (
        <div className="mt-1 space-y-1 text-[11px] text-accent-400">
          {health.config_warnings.map((w) => (
            <div key={w}>⚠ {w}</div>
          ))}
        </div>
      )}
      {watchlistSize != null && (
        <div className="flex items-center justify-between py-1.5 text-xs">
          <span className="text-ink-500">Watchlist</span>
          <span className="font-mono text-ink-300">
            {watchlistSize} symbols{symbolsUnavailable?.length ? ` \u00b7 ${symbolsUnavailable.length} failed` : ""}
          </span>
        </div>
      )}
      {status === "unavailable" && (
        <div className="mt-1 text-[11px] text-accent-400">
          Data provider unavailable: no symbol returned data. Nothing is being substituted.
        </div>
      )}
      {symbolsUnavailable?.length > 0 && (
        <div className="mt-1 space-y-0.5 text-[11px] text-accent-400">
          {symbolsUnavailable.map((sym) => (
            <div key={sym} title={symbolErrors?.[sym]}>
              ⚠ {sym}: {(symbolErrors?.[sym] || "unavailable").replace(/^provider_unavailable:\s*/, "").slice(0, 90)}
            </div>
          ))}
        </div>
      )}
      <StatusRow
        label="Model"
        ok={health?.model_status === "loaded"}
        okLabel="Loaded"
        badLabel="Unavailable"
      />
      <StatusRow label="Inference" ok={!error} okLabel="Running" badLabel="Stopped" />
      <StatusRow label="Last refresh" ok={!error && !isStale} okLabel="Succeeded" badLabel={isStale ? "Stale" : "Failed"} />
      {lastUpdate && (
        <div className="flex items-center justify-between py-1.5 text-xs">
          <span className="text-ink-500">Last successful data</span>
          <span className="font-mono text-ink-300">{formatDateTime(lastUpdate, m)}</span>
        </div>
      )}
      {isStale && !error && (
        <div className="mt-2 text-[11px] text-accent-400">
          Data hasn't refreshed in over {Math.round(staleAfterMs / 1000)}s — check the market feed.
        </div>
      )}
      {error && <div className="mt-2 text-[11px] text-accent-400">{error}</div>}
    </div>
  );
}