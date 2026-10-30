import { useState } from "react";
import Dialog from "./Dialog";
import { resolveMarketInfo } from "../lib/format";

const HINT = {
  IN: "Plain NSE symbols work (the .NS suffix is added for you). Use .BO to add a BSE listing.",
  US: "Use the plain US ticker with no exchange suffix. Share classes work as BRK.B.",
};

/**
 * `onSubmit(symbol)` must resolve on success and reject with an ApiError otherwise. A 503
 * means "could not verify right now" (try again); anything else means "this symbol was refused".
 */
export default function AddStockDialog({ marketInfo, onSubmit, onClose }) {
  const m = resolveMarketInfo(marketInfo);
  const [symbol, setSymbol] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const examples = (m.example_symbols || []).slice(0, 4);

  const submit = async (e) => {
    e.preventDefault();
    const value = symbol.trim();
    if (!value || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      await onSubmit(value);
    } catch (err) {
      setProblem({ temporary: err?.status === 503 || err?.status === 0, text: err?.message || "Could not add this symbol" });
      setBusy(false);
    }
  };

  return (
    <Dialog title={`Add stock to ${m.label}`} onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs text-ink-500">
          Stock symbol
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            disabled={busy}
            placeholder={examples[0] ? `e.g. ${examples[0]}` : "Symbol"}
            autoComplete="off"
            spellCheck={false}
            className="rounded border border-base-700 bg-base-850 px-2.5 py-2 font-mono text-sm uppercase text-ink-100 placeholder:normal-case placeholder:text-ink-500 focus:border-accent-500 focus:outline-none"
          />
        </label>
        <p className="text-[11px] leading-relaxed text-ink-500">
          {HINT[m.market] || ""}
          {examples.length > 0 && <> Examples: {examples.join(", ")}.</>}
        </p>

        {busy && (
          <div role="status" className="text-xs text-ink-300">
            Verifying with the data provider…
          </div>
        )}
        {problem && (
          <div
            role="alert"
            className={`rounded border px-3 py-2 text-xs ${
              problem.temporary ? "border-yellow-700 bg-yellow-900/20 text-yellow-400" : "border-accent-700 bg-accent-900/30 text-accent-400"
            }`}
          >
            {problem.text}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded border border-base-700 px-3 py-1.5 text-xs text-ink-300 hover:bg-base-800 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !symbol.trim()}
            className="rounded bg-accent-600 px-3 py-1.5 text-xs font-medium text-ink-100 hover:bg-accent-500 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </form>
    </Dialog>
  );
}
