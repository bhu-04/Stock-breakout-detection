function Card({ label, value, sub }) {
  return (
    <div className="flex-1 rounded border border-base-800 bg-base-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-500">{label}</div>
      <div className="mt-1.5 font-mono text-2xl font-semibold text-ink-100 tabular">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-ink-500">{sub}</div>}
    </div>
  );
}

export default function SummaryCards({ summary, modelStatus }) {
  if (!summary) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Card
        label="Stocks Monitored"
        value={summary.stocks_monitored}
        sub={summary.failed_symbols ? `${summary.failed_symbols} failed to load` : undefined}
      />
      <Card
        label="High-Probability Opportunities"
        value={summary.high_probability_opportunities}
        sub={`>= ${(summary.alert_threshold * 100).toFixed(0)}% probability`}
      />
      <Card label="Live Update Count" value={summary.live_update_count} />
      <Card
        label="Model Status"
        value={modelStatus === "loaded" ? "Loaded" : "Unavailable"}
        sub={modelStatus === "loaded" ? undefined : "Train a model to enable predictions"}
      />
    </div>
  );
}
