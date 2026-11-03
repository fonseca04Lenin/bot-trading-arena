import { scaleLinear, scaleTime } from "d3-scale";

export type Point = { ts: string; equity: number };
export type Pad = { top: number; right: number; bottom: number; left: number };

export function extent(series: Point[][], baseline: number): [number, number] {
  const values = series.flat().map((p) => p.equity).concat(baseline);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.max(1, Math.abs(hi) * 0.01);
  return [lo - span * 0.08, hi + span * 0.08];
}

export function makeScales(series: Point[][], baseline: number, width: number, height: number, pad: Pad) {
  const times = series.flat().map((p) => new Date(p.ts).getTime());
  const t0 = times.length ? Math.min(...times) : Date.now() - 1;
  const t1 = times.length ? Math.max(...times) : Date.now();
  const x = scaleTime()
    .domain([new Date(t0), new Date(t1 === t0 ? t0 + 1 : t1)])
    .range([pad.left, width - pad.right]);
  const y = scaleLinear().domain(extent(series, baseline)).range([height - pad.bottom, pad.top]);
  return { x, y };
}

/** Spread label y-positions so none overlap by less than `gap` px, keeping order. */
export function spreadLabels(ys: number[], gap: number, min: number, max: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 0; k < order.length; k++) {
    const prev = k === 0 ? min - gap : order[k - 1].y;
    order[k].y = Math.max(order[k].y, prev + gap);
  }
  for (let k = order.length - 1; k >= 0; k--) {
    const next = k === order.length - 1 ? max + gap : order[k + 1].y;
    order[k].y = Math.min(order[k].y, next - gap);
  }
  const out = new Array<number>(ys.length);
  for (const o of order) out[o.i] = o.y;
  return out;
}

export function nearestIndex(points: Point[], ts: string): number {
  const target = new Date(ts).getTime();
  let best = 0;
  let bestD = Infinity;
  points.forEach((p, i) => {
    const d = Math.abs(new Date(p.ts).getTime() - target);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  });
  return best;
}

export const DASHES = ["", "6 3", "1.5 3", "7 3 1.5 3", "12 4"];
