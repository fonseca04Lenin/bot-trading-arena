"use client";

import type { TickerItem } from "@/lib/api";
import { price } from "@/lib/format";
import { useLive } from "./Live";

const LABEL = (s: string) => s.replace("/USD", "");

export function Ticker({ items }: { items: TickerItem[] }) {
  const { prices } = useLive();
  if (!items.length) return <div className="ticker mono page">No prices on the tape yet.</div>;
  const row = items.map((t) => {
    const p = prices[t.symbol] ?? t.price;
    const ch = t.change;
    return (
      <span className="ticker-item" key={t.symbol}>
        {LABEL(t.symbol)} {price(p)}{" "}
        {ch === null ? "" : ch < 0 ? <span className="down">{"▼"}{Math.abs(ch * 100).toFixed(1)}%</span> : <>{"▲"}{(ch * 100).toFixed(1)}%</>}
        {" ·"}
      </span>
    );
  });
  return (
    <div className="ticker" role="region" aria-label="Ticker tape" tabIndex={0}>
      <div className="ticker-track">
        <span>{row}</span>
        <span className="ticker-copy" aria-hidden="true">{row}</span>
      </div>
    </div>
  );
}
