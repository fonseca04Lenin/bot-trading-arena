"use client";

import { useState } from "react";
import { scaleLinear } from "d3-scale";
import type { TradeDetail } from "@/lib/api";
import { price, timeET } from "@/lib/format";

export function TradeChart({ trade }: { trade: TradeDetail }) {
  const [tip, setTip] = useState<number | null>(null);
  const bars = trade.bars;
  const w = 760, h = 300, pad = { t: 14, r: 64, b: 24, l: 8 };
  if (!bars.length) return <p className="deck">No bars on file around this trade.</p>;
  const lo = Math.min(...bars.map((b) => b.l)), hi = Math.max(...bars.map((b) => b.h));
  const y = scaleLinear().domain([lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.05 || 1]).range([h - pad.b, pad.t]);
  const step = (w - pad.l - pad.r) / bars.length;
  const idx = bars.findIndex((b) => new Date(b.ts).getTime() >= new Date(trade.ts).getTime());
  const at = idx === -1 ? bars.length - 1 : idx;
  const buy = trade.side === "BUY" || trade.side === "COVER";
  const cx = pad.l + step * (at + 0.5);
  const ref = trade.price ?? bars[at].c;
  return (
    <div className="chart-wrap">
      <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img"
        aria-label={`Five-minute bars around the ${trade.side} of ${trade.symbol} at ${price(ref)}`}>
        {y.ticks(4).map((t) => <text key={t} className="axis" x={w - pad.r + 8} y={y(t) + 4}>{price(t)}</text>)}
        <line x1={cx} x2={cx} y1={pad.t} y2={h - pad.b} stroke="var(--ink)" strokeWidth="1" strokeDasharray="2 3" />
        {bars.map((b, i) => {
          const x = pad.l + step * (i + 0.5);
          return (
            <g key={b.ts} tabIndex={0} onMouseEnter={() => setTip(i)} onFocus={() => setTip(i)} onMouseLeave={() => setTip(null)} onBlur={() => setTip(null)}>
              <rect x={x - step / 2} y={pad.t} width={step} height={h - pad.t - pad.b} fill="transparent" />
              <line x1={x} x2={x} y1={y(b.h)} y2={y(b.l)} stroke="var(--ink)" strokeWidth="1.5" />
              <line x1={x - step * 0.3} x2={x} y1={y(b.o)} y2={y(b.o)} stroke="var(--ink)" strokeWidth="1.5" />
              <line x1={x} x2={x + step * 0.3} y1={y(b.c)} y2={y(b.c)} stroke="var(--ink)" strokeWidth="1.5" />
            </g>
          );
        })}
        <path d={buy ? `M${cx} ${y(ref) + 2} l-7 12 h14z` : `M${cx} ${y(ref) - 2} l-7 -12 h14z`} fill={buy ? "var(--ink)" : "var(--spot)"} />
        <text className="axis" x={cx + 10} y={buy ? y(ref) + 26 : y(ref) - 16}>{trade.side} {price(ref)}</text>
      </svg>
      {tip !== null && (
        <div className="tip" style={{ left: `${(pad.l + step * (tip + 0.5)) / w * 100}%`, top: 4 }}>
          {timeET(bars[tip].ts)}<br />O {price(bars[tip].o)} H {price(bars[tip].h)}<br />L {price(bars[tip].l)} C {price(bars[tip].c)}
        </div>
      )}
      <table className="sr-only">
        <caption>Bars around the trade</caption>
        <thead><tr><th scope="col">Time</th><th scope="col">Open</th><th scope="col">High</th><th scope="col">Low</th><th scope="col">Close</th></tr></thead>
        <tbody>{bars.map((b) => <tr key={b.ts}><th scope="row">{timeET(b.ts)}</th><td>{b.o}</td><td>{b.h}</td><td>{b.l}</td><td>{b.c}</td></tr>)}</tbody>
      </table>
    </div>
  );
}
