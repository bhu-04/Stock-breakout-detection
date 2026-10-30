import MarketSelect from "./MarketSelect";
import { formatTime, resolveMarketInfo, sessionLabel, timeZoneLabel } from "../lib/format";

const STATUS_LABEL = {
  live: "LIVE",
  delayed: "DELAYED",
  demo: "DEMO DATA",
  partial: "PARTIAL DATA",
  unavailable: "DATA UNAVAILABLE",
};

const STATUS_COLOR = {
  live: "bg-up",
  delayed: "bg-yellow-500",
  demo: "bg-accent-400",
  partial: "bg-yellow-500",
  unavailable: "bg-red-600",
};

function Spinner() {
  return <span aria-hidden="true" className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ink-500 border-t-transparent" />;
}

/**
 * `marketInfo` describes the market of the data CURRENTLY on screen. While the selected market
 * is still loading it is null, so the header never labels old data with the new market's name.
 */
export default function Header({
  markets,
  market,
  onMarketChange,
  switching,
  pendingLabel,
  symbolCount,
  lastUpdate,
  dataStatus,
  dataFeed,
  marketInfo,
}) {
  const m = resolveMarketInfo(marketInfo);
  const session = marketInfo ? sessionLabel(m.session, m) : null;
  const isStale = lastUpdate ? Date.now() - new Date(lastUpdate).getTime() > 60000 : false;
  const status = dataStatus || "demo";
  const label = (STATUS_LABEL[status] || status.toUpperCase()) + (dataFeed && status === "live" ? ` • ${dataFeed.toUpperCase()}` : "");

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-base-800 px-6 py-4">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-accent-600 font-mono text-sm font-bold text-ink-100">
          B
        </div>
        <div>
          <h1 className="text-[15px] font-semibold leading-none text-ink-100">Breakout Monitor</h1>
          <p className="mt-1 text-[11px] leading-none text-ink-500">AI-based stock breakout detection</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
        <MarketSelect markets={markets} value={market} onChange={onMarketChange} />

        {switching || !marketInfo ? (
          <div role="status" className="flex items-center gap-2 text-ink-500">
            <Spinner />
            <span>Loading {pendingLabel || "market"}…</span>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className={`h-1.5 w-1.5 rounded-full ${STATUS_COLOR[status] || "bg-accent-400"}`} />
              <span className="font-mono text-ink-300">{label}</span>
            </div>
            <div className="hidden items-center gap-2 sm:flex">
              <span data-testid="market-badge" className="rounded bg-base-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-300">
                {m.label}
              </span>
              {session && <span className={m.session?.state === "open" ? "text-up" : "text-ink-500"}>{session}</span>}
            </div>
            <div className="hidden text-ink-500 sm:block">{symbolCount ?? "—"} symbols</div>
            <div className="hidden text-ink-500 md:block" title="Time of the last successful data refresh (not the current time)">
              Last update {lastUpdate ? `${formatTime(lastUpdate, m)} ${timeZoneLabel(m.timezone)}` : "—"}
              {isStale && <span className="ml-1.5 text-accent-400">(stale)</span>}
            </div>
          </>
        )}
      </div>
    </header>
  );
}
