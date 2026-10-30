import { FALLBACK_MARKETS } from "../lib/markets";

/** Header dropdown that selects the market for the WHOLE app. */
export default function MarketSelect({ markets, value, onChange, disabled }) {
  const options = markets && markets.length ? markets : FALLBACK_MARKETS;
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="market-select" className="text-[11px] uppercase tracking-wide text-ink-500">
        Market
      </label>
      <select
        id="market-select"
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-base-700 bg-base-850 px-2.5 py-1.5 text-xs font-medium text-ink-100 focus:border-accent-500 focus:outline-none disabled:opacity-60"
      >
        {options.map((m) => (
          <option key={m.market} value={m.market}>
            {m.option_label}
          </option>
        ))}
      </select>
    </div>
  );
}
