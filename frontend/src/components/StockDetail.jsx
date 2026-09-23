import { useEffect, useState } from "react";
import { api } from "../lib/api";
import CandlestickChart from "./CandlestickChart";

function IndicatorRow({ label, value, suffix = "" }) {
  return (
    <div className="flex items-center justify-between border-b border-base-850 py-1.5 text-xs last:border-0">
      <span className="text-ink-500">{label}</span>
      <span className="font-mono tabular text-ink-100">{value ?? "—"}{value !== null && value !== undefined ? suffix : ""}</span>
    </div>
  );
}

export default function StockDetail({ symbol }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .stockDetail(symbol, 180)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (!symbol) {
    return (
      <div className="flex h-full items-center justify-center rounded border border-base-800 bg-base-900 p-8 text-center text-sm text-ink-500">
        Select a symbol from the table to view its chart and breakout signal.
      </div>
    );
  }

  if (loading && !detail) {
    return (
      <div className="flex h-full items-center justify-center rounded border border-base-800 bg-base-900 p-8 text-sm text-ink-500">
        Loading {symbol}…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded border border-accent-700 bg-accent-900/30 p-4 text-sm text-accent-400">
        Couldn't load {symbol}: {error}
      </div>
    );
  }

  if (!detail) return null;

  const probPct = detail.breakout_probability !== null ? Math.round(detail.breakout_probability * 100) : null;

  return (
    <div className="rounded border border-base-800 bg-base-900">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-base-800 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-ink-100">{detail.symbol}</h2>
            <span className="rounded bg-base-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-500">
              {detail.is_live_data ? "LIVE" : "DEMO"}
            </span>
          </div>
          <div className="mt-0.5 font-mono text-2xl tabular text-ink-100">
            ${detail.candles[detail.candles.length - 1]?.close.toFixed(2)}
          </div>
        </div>
        {probPct !== null ? (
          <div className="rounded border border-base-700 px-3 py-2 text-right">
            <div className="text-[10px] uppercase tracking-wide text-ink-500">Breakout Probability</div>
            <div className={`font-mono text-xl font-semibold ${probPct >= 65 ? "text-accent-400" : "text-ink-100"}`}>
              {probPct}%
            </div>
          </div>
        ) : (
          <div className="rounded border border-base-700 px-3 py-2 text-right text-xs text-ink-500">
            Model unavailable
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[1fr_220px]">
        <CandlestickChart
          candles={detail.candles}
          resistance={detail.resistance}
          confirmationPrice={detail.breakout_confirmation_price}
        />

        <div className="flex flex-col gap-4">
          <div>
            <div className="mb-1.5 text-[11px] uppercase tracking-wide text-ink-500">Indicators</div>
            <IndicatorRow label="RSI (14)" value={detail.indicators.rsi_14} />
            <IndicatorRow label="MACD" value={detail.indicators.macd} />
            <IndicatorRow label="MACD Signal" value={detail.indicators.macd_signal} />
            <IndicatorRow label="ATR (14)" value={detail.indicators.atr_14} />
            <IndicatorRow label="Rel. Volume" value={detail.indicators.relative_volume} suffix="×" />
            <IndicatorRow label="VWAP Dev." value={detail.indicators.vwap_deviation_pct} suffix="%" />
          </div>

          <div>
            <div className="mb-1.5 text-[11px] uppercase tracking-wide text-ink-500">Levels</div>
            <IndicatorRow label="Resistance" value={detail.resistance} />
            <IndicatorRow label="Confirmation Zone" value={detail.breakout_confirmation_price} />
          </div>

          {detail.model && (
            <div>
              <div className="mb-1.5 text-[11px] uppercase tracking-wide text-ink-500">Model</div>
              <IndicatorRow label="Model" value={detail.model.model_name} />
              <IndicatorRow label="Version" value={detail.model.version} />
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-base-800 px-4 py-2.5 text-[11px] text-ink-500">
        Breakout probability is a model estimate based on current market features. It is not a guarantee of future price movement.
      </div>
    </div>
  );
}
