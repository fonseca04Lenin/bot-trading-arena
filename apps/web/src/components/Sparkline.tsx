import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";

export function Sparkline({ values, label, color = "var(--ink)" }: { values: number[]; label: string; color?: string }) {
  const w = 80, h = 20;
  if (values.length < 2) return <span className="mono" aria-label={`${label}: not enough history`}>{"—"}</span>;
  const x = scaleLinear().domain([0, values.length - 1]).range([2, w - 4]);
  const lo = Math.min(...values), hi = Math.max(...values);
  const y = scaleLinear().domain([lo, hi === lo ? lo + 1 : hi]).range([h - 3, 3]);
  const d = line<number>().x((_, i) => x(i)).y((v) => y(v))(values) ?? "";
  const down = values[values.length - 1] < values[values.length - 2];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {down && <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2.6" fill="var(--spot)" />}
    </svg>
  );
}
