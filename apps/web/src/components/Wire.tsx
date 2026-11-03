"use client";

import { useState } from "react";
import { PUBLIC_API_URL, type Trade } from "@/lib/api";
import { price, qty, timeET } from "@/lib/format";
import { botInk } from "@/lib/colors";
import { Silks } from "./Silks";

export function WireEntry({ t, fresh }: { t: Trade; fresh?: boolean }) {
  const scratched = t.status === "rejected";
  const verb = t.side === "BUY" ? "BOUGHT" : "SOLD";
  return (
    <li className={fresh ? "fresh" : undefined} style={{ "--c": botInk(t.bot_slug) } as React.CSSProperties}>
      <div className="meta">
        <span>{timeET(t.ts)}</span>
        <Silks silks={t.silks} size={16} />
        <a className="who" href={`/bots/${t.bot_slug}`}>{t.bot_name}</a>
        {scratched ? (
          <span className="scratched">SCRATCHED {t.side} {t.symbol}</span>
        ) : (
          <a className="act" href={`/trades/${t.id}`}>
            {verb} {qty(t.qty)} {t.symbol.replace("/USD", "")} @ {t.price ? price(t.price) : "—"}
          </a>
        )}
      </div>
      <p className="why">{scratched ? `Refused: ${t.reject_reason ?? "no reason given"}. ` : ""}{t.rationale}</p>
    </li>
  );
}

export function Wire({ initial, fresh = [], bot }: { initial: Trade[]; fresh?: Trade[]; bot?: string }) {
  const [older, setOlder] = useState<Trade[]>([]);
  const [done, setDone] = useState(false);
  const seen = new Set<string>();
  const items = [...fresh.filter((t) => !bot || t.bot_slug === bot), ...initial, ...older].filter((t) => {
    if (seen.has(t.id)) return false;
    seen.add(t.id);
    return true;
  });
  const freshIds = new Set(fresh.map((t) => t.id));

  const more = async () => {
    const last = items[items.length - 1];
    const q = new URLSearchParams({ limit: "20", before: last.ts, ...(bot ? { bot } : {}) });
    const res = await fetch(`${PUBLIC_API_URL}/api/trades?${q}`);
    const body = (await res.json()) as { items: Trade[]; next_before: string | null };
    setOlder((o) => [...o, ...body.items]);
    if (!body.next_before) setDone(true);
  };

  if (!items.length) return <p className="deck">No trades yet today. The bell rings at 9:30 a.m. ET.</p>;
  return (
    <>
      <ul className="wire" aria-live="polite">
        {items.map((t) => <WireEntry key={t.id} t={t} fresh={freshIds.has(t.id)} />)}
      </ul>
      {!done && items.length >= 12 && <button type="button" className="more" onClick={more}>More from the Wire</button>}
    </>
  );
}
