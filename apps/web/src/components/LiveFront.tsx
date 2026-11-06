"use client";

import { useEffect, useRef, useState } from "react";
import { PUBLIC_API_URL, toPoints, type FrontPage } from "@/lib/api";
import { pct } from "@/lib/format";
import { EquityChart } from "./EquityChart";
import { TheForm } from "./Form";
import { useLive } from "./Live";
import { Wire } from "./Wire";

export function LiveFront({ initial }: { initial: FrontPage }) {
  const [page, setPage] = useState(initial);
  const { tick, reconnects, trades } = useLive();
  const last = useRef(0);

  useEffect(() => {
    // Refetch on equity ticks (throttled) and after every reconnect so nothing is missed.
    if (Date.now() - last.current < 5000 && reconnects === 0) return;
    last.current = Date.now();
    fetch(`${PUBLIC_API_URL}/api/front-page`).then((r) => (r.ok ? r.json() : null)).then((p) => p && setPage(p)).catch(() => {});
  }, [tick, reconnects]);

  const lead = page.leaderboard[0];
  const series = page.leaderboard.map((b) => ({
    slug: b.slug, name: b.name, silks: b.silks, leader: b === lead, points: toPoints(page.equity[b.slug] ?? []),
  }));
  const summary = lead
    ? `Equity of all seven bots over the past week. ${lead.name} leads at ${pct(lead.return).text}.`
    : "Equity chart";

  return (
    <>
      <section className="col c-8" aria-labelledby="form-h">
        <div className="section-head" style={{ "--tag": "var(--pink)" } as React.CSSProperties}><h2 id="form-h">The Form</h2><span className="kicker">Ranked by return since launch</span></div>
        <TheForm bots={page.leaderboard} />
        <div className="section-head" style={{ marginTop: 32, "--tag": "var(--sky)" } as React.CSSProperties}>
          <h2>The Race</h2><span className="kicker">Equity, past week</span>
        </div>
        <EquityChart series={series} summary={summary} />
      </section>
      <aside className="col c-4" aria-labelledby="wire-h">
        <div className="section-head" style={{ "--tag": "var(--mint)" } as React.CSSProperties}><h2 id="wire-h">The Wire</h2><span className="kicker">Every trade, with a reason</span></div>
        {page.market_note && <p className="margin-note">The Analyst notes: {page.market_note}</p>}
        <Wire initial={page.trades} fresh={trades} />
      </aside>
    </>
  );
}
