import { describe, expect, it } from "vitest";
import { extent, makeScales, nearestIndex, spreadLabels } from "./scale";

const pts = [
  { ts: "2026-01-01T00:00:00Z", equity: 100 },
  { ts: "2026-01-02T00:00:00Z", equity: 110 },
];

describe("scale helpers", () => {
  it("includes the baseline in the extent", () => {
    const [lo, hi] = extent([pts], 90);
    expect(lo).toBeLessThan(90);
    expect(hi).toBeGreaterThan(110);
  });
  it("maps time and value into the plot box", () => {
    const { x, y } = makeScales([pts], 100, 400, 200, { top: 10, right: 50, bottom: 10, left: 10 });
    expect(x(new Date(pts[0].ts))).toBe(10);
    expect(x(new Date(pts[1].ts))).toBe(350);
    expect(y(110)).toBeLessThan(y(100));
  });
  it("copes with a single flat point", () => {
    const { y } = makeScales([[pts[0]]], 100, 400, 200, { top: 10, right: 50, bottom: 10, left: 10 });
    expect(Number.isFinite(y(100))).toBe(true);
  });
  it("separates overlapping labels but keeps their order", () => {
    const out = spreadLabels([50, 51, 52, 200], 14, 10, 300);
    for (let i = 1; i < out.length; i++) expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(14 - 1e-9);
    expect(out[3]).toBe(200);
  });
  it("finds the nearest point in time", () => {
    expect(nearestIndex(pts, "2026-01-01T20:00:00Z")).toBe(1);
    expect(nearestIndex(pts, "2025-12-31T00:00:00Z")).toBe(0);
  });
});
