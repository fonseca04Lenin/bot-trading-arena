"use client";

import { useEffect, useRef, useState } from "react";
import { line, area } from "d3-shape";
import type { Silks as SilksT, Trade } from "@/lib/api";
import { dollars, price, timeET } from "@/lib/format";
import { botInk } from "@/lib/colors";
import { DASHES, makeScales, nearestIndex, spreadLabels, type Point } from "@/lib/scale";

export type Series = { slug: string; name: string; silks: SilksT; points: Point[]; leader?: boolean };

const BASELINE = 100000;

function useWidth(initial = 760): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function EquityChart({ series, trades = [], height = 340, summary }: {
  series: Series[]; trades?: Trade[]; height?: number; summary: string;
}) {
  const [ref, width] = useWidth();
  const [tip, setTip] = useState<{ x: number; y: number; trade: Trade } | null>(null);
  const narrow = width < 520;
  const pad = { top: 14, right: narrow ? 132 : 160, bottom: 22, left: 8 };
  const all = series.map((s) => s.points);
  if (all.every((p) => p.length < 2)) {
    return <p className="deck">Setting type… the chart fills in once a few five-minute snapshots are on file.</p>;
  }
  const { x, y } = makeScales(all, BASELINE, width, height, pad);
  const path = line<Point>().x((p) => x(new Date(p.ts))).y((p) => y(p.equity));
  const ticks = y.ticks(4);
  const ends = series.map((s) => (s.points.length ? y(s.points[s.points.length - 1].equity) : height / 2));
  const labelY = spreadLabels(ends, 14, pad.top + 6, height - pad.bottom);
  const leader = series.find((s) => s.leader);

  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary}>
        <defs>
          <pattern id="halftone" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(30)">
            <circle cx="2.5" cy="2.5" r="1.25" fill={leader ? botInk(leader.slug) : "var(--ink)"} />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <text key={t} className="axis" x={width - 2} y={y(t) + 4} textAnchor="end">
            {dollars(t)}
          </text>
        ))}
        {leader && leader.points.length > 1 && (
          <path
            d={area<Point>().x((p) => x(new Date(p.ts))).y0(y(BASELINE)).y1((p) => y(p.equity))(leader.points) ?? ""}
            fill="url(#halftone)" opacity="0.85"
          />
        )}
        <line x1={pad.left} x2={width - pad.right} y1={y(BASELINE)} y2={y(BASELINE)} stroke="var(--ink)" strokeWidth="1.2"
          strokeDasharray="2 4" strokeLinecap="round" filter="url(#wobble)" />
        <text className="axis note" x={pad.left + 2} y={y(BASELINE) - 6}>where everyone started</text>
        <g filter="url(#wobble)" strokeLinecap="round" strokeLinejoin="round">
          {series.map((s, i) => (
            <path key={s.slug} d={path(s.points) ?? ""} fill="none" stroke={botInk(s.slug)} strokeWidth={s.leader ? 3.4 : 2.6}
              strokeDasharray={DASHES[i % DASHES.length]} />
          ))}
        </g>
        {series.map((s) => {
          const last = s.points[s.points.length - 1];
          return last ? <circle key={s.slug} cx={x(new Date(last.ts))} cy={y(last.equity)} r="4.5" fill={botInk(s.slug)} stroke="var(--paper)" strokeWidth="1.5" /> : null;
        })}
        {series.map((s, i) => (
          <text key={s.slug} className="label" x={width - pad.right + 8} y={labelY[i] + 4}>
            <tspan fill={botInk(s.slug)}>{"\u25CF "}</tspan>{s.name.replace("The ", "")}
          </text>
        ))}
        {leader && leader.points.length > 1 && !narrow && (() => {
          const last = leader.points[leader.points.length - 1];
          const ex = x(new Date(last.ts)), ey = y(last.equity);
          return (
            <g className="hand-note" aria-hidden="true">
              <text x={ex - 190} y={ey + 22}>out in front!</text>
              <path d={`M${ex - 100} ${ey + 14} C ${ex - 70} ${ey + 6}, ${ex - 40} ${ey - 2}, ${ex - 14} ${ey - 4}`} fill="none" strokeWidth="2" strokeLinecap="round" />
              <path d={`M${ex - 24} ${ey - 11} L ${ex - 13} ${ey - 4} L ${ex - 25} ${ey + 3}`} fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </g>
          );
        })()}
        {trades.map((t) => {
          const s = series.find((q) => q.slug === t.bot_slug);
          if (!s || t.status !== "filled" || !s.points.length) return null;
          const p = s.points[nearestIndex(s.points, t.ts)];
          const cx = x(new Date(p.ts)), cy = y(p.equity);
          const buy = t.side === "BUY" || t.side === "COVER";
          const d = buy ? `M${cx} ${cy - 7} L${cx - 5} ${cy + 1} L${cx + 5} ${cy + 1}Z` : `M${cx} ${cy + 7} L${cx - 5} ${cy - 1} L${cx + 5} ${cy - 1}Z`;
          return (
            <g key={t.id} className="mark" tabIndex={0} role="img"
              aria-label={`${t.side} ${t.symbol} at ${t.price ? price(t.price) : "n/a"}, ${timeET(t.ts)}`}
              onMouseEnter={() => setTip({ x: cx, y: cy, trade: t })} onFocus={() => setTip({ x: cx, y: cy, trade: t })}
              onMouseLeave={() => setTip(null)} onBlur={() => setTip(null)}>
              <circle cx={cx} cy={cy} r="11" fill="transparent" />
              <path d={d} fill={buy ? "var(--ink)" : "var(--spot)"} stroke="var(--paper)" strokeWidth="1" />
            </g>
          );
        })}
      </svg>
      {tip && (
        <div className="tip" style={{ left: Math.min(tip.x + 10, width - 250), top: Math.max(0, tip.y - 56) }}>
          {tip.trade.side} {tip.trade.symbol} @ {tip.trade.price ? price(tip.trade.price) : "—"}<br />{timeET(tip.trade.ts)}
        </div>
      )}
      <table className="sr-only">
        <caption>{summary}</caption>
        <thead><tr><th scope="col">Bot</th><th scope="col">Latest equity</th></tr></thead>
        <tbody>
          {series.map((s) => (
            <tr key={s.slug}><th scope="row">{s.name}</th><td>{s.points.length ? dollars(s.points[s.points.length - 1].equity) : "none"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
