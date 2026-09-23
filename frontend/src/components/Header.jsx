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

export default function Header({ health, lastUpdate, dataStatus, dataFeed }) {
  const isStale = lastUpdate ? Date.now() - new Date(lastUpdate).getTime() > 60000 : false;
  const status = dataStatus || "demo";
  const label = (STATUS_LABEL[status] || status.toUpperCase()) + (dataFeed && status === "live" ? ` • ${dataFeed.toUpperCase()}` : "");

  return (
    <header className="flex items-center justify-between border-b border-base-800 px-6 py-4">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-accent-600 font-mono text-sm font-bold text-ink-100">
          B
        </div>
        <div>
          <h1 className="text-[15px] font-semibold leading-none text-ink-100">Breakout Monitor</h1>
          <p className="mt-1 text-[11px] leading-none text-ink-500">AI-based stock breakout detection</p>
        </div>
      </div>

      <div className="flex items-center gap-5 text-xs">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full ${STATUS_COLOR[status] || "bg-accent-400"}`} />
          <span className="font-mono text-ink-300">{label}</span>
        </div>
        <div className="hidden text-ink-500 sm:block">
          {health?.watchlist_symbols_count ?? health?.watchlist_size ?? "—"} symbols
        </div>
        <div className="hidden text-ink-500 md:block">
          Updated {lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : "—"}
          {isStale && <span className="ml-1.5 text-accent-400">(stale)</span>}
        </div>
      </div>
    </header>
  );
}