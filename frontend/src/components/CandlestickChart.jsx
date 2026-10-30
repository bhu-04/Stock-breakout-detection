import { useMemo } from "react";
import { formatDateTime, formatTime, resolveMarketInfo } from "../lib/format";
import {
  ComposedChart,
  Bar,
  Cell,
  ReferenceLine,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const UP = "#3fb37f";
const DOWN = "#d1453d";

// Custom shape for a range-Bar whose dataKey is [low, high]. Recharts gives
// us the pixel y/height for that [low, high] span; we derive the local
// px-per-unit scale from it and use that to place the open/close body and
// the high/low wick precisely, without depending on any chart-internal
// axis map (works identically across Recharts v2 and v3).
function CandleShape(props) {
  const { x, y, width, height, payload } = props;
  const { open, close, high, low } = payload;
  if (high === low) return null;

  const pxPerUnit = height / (high - low);
  const bodyTopValue = Math.max(open, close);
  const bodyBottomValue = Math.min(open, close);
  const bodyTop = y + (high - bodyTopValue) * pxPerUnit;
  const bodyHeight = Math.max(1, (bodyTopValue - bodyBottomValue) * pxPerUnit);
  const isUp = close >= open;
  const color = isUp ? UP : DOWN;
  const centerX = x + width / 2;
  const bodyWidth = Math.max(2, width * 0.7);
  const bodyX = centerX - bodyWidth / 2;

  return (
    <g>
      <line x1={centerX} x2={centerX} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={bodyX} y={bodyTop} width={bodyWidth} height={bodyHeight} fill={color} />
    </g>
  );
}

function ChartTooltip({ active, payload, marketInfo }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded border border-base-700 bg-base-900 px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-mono text-ink-500">{formatDateTime(d.timestamp, marketInfo)}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular font-mono">
        <span className="text-ink-500">O</span><span>{d.open.toFixed(2)}</span>
        <span className="text-ink-500">H</span><span>{d.high.toFixed(2)}</span>
        <span className="text-ink-500">L</span><span>{d.low.toFixed(2)}</span>
        <span className="text-ink-500">C</span>
        <span className={d.close >= d.open ? "text-up" : "text-down"}>{d.close.toFixed(2)}</span>
        <span className="text-ink-500">Vol</span><span>{(d.volume / 1000).toFixed(0)}k</span>
      </div>
    </div>
  );
}

export default function CandlestickChart({ candles, resistance, confirmationPrice, marketInfo }) {
  const m = resolveMarketInfo(marketInfo);
  const data = useMemo(
    () => candles.map((c) => ({ ...c, range: [c.low, c.high] })),
    [candles]
  );

  const yDomain = useMemo(() => {
    const highs = data.map((d) => d.high);
    const lows = data.map((d) => d.low);
    const max = Math.max(...highs, resistance || 0, confirmationPrice || 0);
    const min = Math.min(...lows);
    const pad = (max - min) * 0.08 || 1;
    return [min - pad, max + pad];
  }, [data, resistance, confirmationPrice]);

  const maxVolume = useMemo(() => Math.max(...data.map((d) => d.volume)), [data]);

  return (
    <div className="flex flex-col gap-1">
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="timestamp"
            tickFormatter={(ts) => formatTime(ts, m)}
            tick={{ fill: "#8b8a87", fontSize: 11 }}
            axisLine={{ stroke: "#26272c" }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            domain={yDomain}
            tick={{ fill: "#8b8a87", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={56}
            tickFormatter={(v) => v.toFixed(0)}
          />
          <Tooltip content={<ChartTooltip marketInfo={m} />} cursor={{ stroke: "#35373d" }} />
          {resistance ? (
            <ReferenceLine
              y={resistance}
              stroke="#8b8a87"
              strokeDasharray="4 4"
              label={{ value: "Resistance", position: "insideTopRight", fill: "#8b8a87", fontSize: 10 }}
            />
          ) : null}
          {confirmationPrice ? (
            <ReferenceLine
              y={confirmationPrice}
              stroke="#c22e2e"
              strokeDasharray="4 4"
              label={{ value: "Confirmation", position: "insideBottomRight", fill: "#e6483f", fontSize: 10 }}
            />
          ) : null}
          <Bar dataKey="range" shape={CandleShape} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <ResponsiveContainer width="100%" height={90}>
        <ComposedChart data={data} margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
          <XAxis dataKey="timestamp" hide />
          <YAxis domain={[0, maxVolume * 1.1]} hide />
          <Tooltip content={() => null} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          <Bar dataKey="volume" isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.close >= d.open ? UP : DOWN} fillOpacity={0.7} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
