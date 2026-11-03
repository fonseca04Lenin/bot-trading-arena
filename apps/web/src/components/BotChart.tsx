"use client";

import { useEffect, useState } from "react";
import { PUBLIC_API_URL, type Bot, type EquityPoint, type Trade } from "@/lib/api";
import { pct } from "@/lib/format";
import { EquityChart } from "./EquityChart";
import { useLive } from "./Live";

const RANGES = ["1D", "1W", "1M", "ALL"] as const;

export function BotChart({ bot, trades, initial }: { bot: Bot; trades: Trade[]; initial: EquityPoint[] }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("ALL");
  const [points, setPoints] = useState(initial);
  const { tick, reconnects } = useLive();

  useEffect(() => {
    fetch(`${PUBLIC_API_URL}/api/bots/${bot.slug}/equity?range=${range}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => b && setPoints(b.points))
      .catch(() => {});
  }, [range, bot.slug, tick, reconnects]);

  return (
    <>
      <div className="section-head">
        <h2>The Run</h2>
        <div className="tabs" role="group" aria-label="Chart range">
          {RANGES.map((r) => <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{r}</button>)}
        </div>
      </div>
      <EquityChart
        series={[{ slug: bot.slug, name: bot.name, silks: bot.silks, points, leader: true }]}
        trades={trades.filter((t) => t.bot_slug === bot.slug)}
        summary={`${bot.name} equity over ${range}, ${pct(bot.return).text} since launch. Triangles mark trades.`}
      />
    </>
  );
}
