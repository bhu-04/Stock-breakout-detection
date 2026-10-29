import { useMemo, useState } from "react";
import { formatPrice, formatTime, timeZoneLabel, resolveMarketInfo } from "../lib/format";

const COLUMNS = [
  { key: "rank", label: "Rank" },
  { key: "symbol", label: "Symbol" },
  { key: "breakout_probability", label: "Breakout Prob." },
  { key: "current_price", label: "Price" },
  { key: "rsi", label: "RSI" },
  { key: "relative_volume", label: "Rel. Vol" },
  { key: "trend_signal", label: "Trend Signal" },
  { key: "distance_from_resistance_pct", label: "Dist. Resistance" },
  { key: "last_updated", label: "Updated" },
];

function ProbabilityBar({ value, isAlert }) {
  if (value === null || value === undefined) {
    return <span className="text-ink-500">—</span>;
  }
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-base-700">
        <div
          className={`h-full ${isAlert ? "bg-accent-500" : "bg-ink-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`font-mono tabular text-xs ${isAlert ? "text-accent-400 font-semibold" : "text-ink-300"}`}>
        {pct}%
      </span>
    </div>
  );
}

export default function OpportunityTable({ opportunities, onSelect, selectedSymbol, marketInfo }) {
  const m = resolveMarketInfo(marketInfo);
  const [search, setSearch] = useState("");
  const [minProb, setMinProb] = useState(0);
  const [sortKey, setSortKey] = useState("breakout_probability");
  const [sortDir, setSortDir] = useState("desc");

  const filtered = useMemo(() => {
    let rows = opportunities.filter((o) => o.symbol.toLowerCase().includes(search.toLowerCase()));
    rows = rows.filter((o) => (o.breakout_probability ?? -1) * 100 >= minProb || o.breakout_probability === null && minProb === 0);
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return rows;
  }, [opportunities, search, minProb, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="rounded border border-base-800 bg-base-900">
      <div className="flex flex-wrap items-center gap-3 border-b border-base-800 px-4 py-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search symbol…"
          className="w-40 rounded border border-base-700 bg-base-850 px-2.5 py-1.5 text-xs text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none"
        />
        <div className="flex items-center gap-2 text-xs text-ink-500">
          <span>Min probability</span>
          <input
            type="range"
            min={0}
            max={100}
            value={minProb}
            onChange={(e) => setMinProb(Number(e.target.value))}
            className="accent-accent-500"
          />
          <span className="font-mono text-ink-300 tabular w-8">{minProb}%</span>
        </div>
        <div className="ml-auto text-xs text-ink-500">{filtered.length} of {opportunities.length}</div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-xs">
          <thead>
            <tr className="border-b border-base-800 text-ink-500">
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => toggleSort(c.key)}
                  className="cursor-pointer select-none whitespace-nowrap px-4 py-2 font-medium hover:text-ink-300"
                >
                  {c.label}
                  {sortKey === c.key && <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((o) => (
              <tr
                key={o.symbol}
                onClick={() => onSelect(o.symbol)}
                className={`cursor-pointer border-b border-base-850 transition-colors hover:bg-base-850 ${selectedSymbol === o.symbol ? "bg-base-850" : ""
                  }`}
              >
                <td className="px-4 py-2.5 font-mono text-ink-500">{o.rank ?? "—"}</td>
                <td className="px-4 py-2.5 font-semibold text-ink-100">{o.symbol}</td>
                <td className="px-4 py-2.5">
                  <ProbabilityBar value={o.breakout_probability} isAlert={o.is_alert} />
                </td>
                <td className="px-4 py-2.5 font-mono tabular text-ink-300">{formatPrice(o.current_price, m)}</td>
                <td className="px-4 py-2.5 font-mono tabular text-ink-300">{o.rsi ?? "—"}</td>
                <td className="px-4 py-2.5 font-mono tabular text-ink-300">{o.relative_volume ? `${o.relative_volume}×` : "—"}</td>
                <td className="px-4 py-2.5 text-ink-300">{o.trend_signal}</td>
                <td className="px-4 py-2.5 font-mono tabular text-ink-300">
                  {o.distance_from_resistance_pct !== null ? `${o.distance_from_resistance_pct}%` : "—"}
                </td>
                <td className="px-4 py-2.5 font-mono text-ink-500">
                  {formatTime(o.last_updated, m)} {timeZoneLabel(m.timezone)}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-8 text-center text-ink-500">
                  No opportunities match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}