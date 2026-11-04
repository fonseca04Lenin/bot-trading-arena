import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BotChart } from "@/components/BotChart";
import { Term } from "@/components/Glossary";
import { Silks } from "@/components/Silks";
import { Wire } from "@/components/Wire";
import { ApiError, get, toPoints, type BotDetail, type EquityPoint, type Trade } from "@/lib/api";
import { dollars, pct, plainPct, price, qty, ratio } from "@/lib/format";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: `Form Guide: ${slug}` };
}

export default async function BotPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let bot: BotDetail, trades: { items: Trade[] }, eq: { points: EquityPoint[] };
  try {
    [bot, trades, eq] = await Promise.all([
      get<BotDetail>(`/api/bots/${slug}`),
      get<{ items: Trade[] }>(`/api/trades?bot=${slug}&limit=20`),
      get<{ points: EquityPoint[] }>(`/api/bots/${slug}/equity?range=ALL`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && e.message.endsWith("404.")) notFound();
    return <section className="col"><h1 className="headline">Form Guide unavailable</h1><p className="deck">{e instanceof Error ? e.message : "The wire is down."}</p></section>;
  }
  void toPoints;
  const down = bot.return < 0;
  return (
    <div className="front">
      <section className="col c-8">
        <p className="kicker">Form Guide &middot; rank {bot.rank} of 5</p>
        <h1 className="headline" style={{ display: "flex", gap: 16, alignItems: "center" }}><Silks silks={bot.silks} size={48} title={`${bot.name} silks`} />{bot.name}</h1>
        <p className="prose">{bot.description}</p>
        <BotChart bot={bot} trades={trades.items} initial={eq.points} />
      </section>
      <aside className="col c-4">
        <div className="section-head"><h2>The Numbers</h2></div>
        <dl className="dl">
          <dt>Equity</dt><dd>{dollars(bot.equity)}</dd>
          <dt>Return</dt><dd className={down ? "down" : undefined}>{pct(bot.return).text}</dd>
          <dt>Today</dt><dd className={(bot.today ?? 0) < 0 ? "down" : undefined}>{pct(bot.today).text}</dd>
          <dt><Term id="sharpe">Sharpe</Term></dt><dd>{ratio(bot.sharpe)}</dd>
          <dt><Term id="drawdown">Max drawdown</Term></dt><dd>{plainPct(bot.max_drawdown)}</dd>
          <dt><Term id="win-rate">Win rate</Term></dt><dd>{plainPct(bot.win_rate, 0)}</dd>
          <dt>Trades</dt><dd>{bot.trades}</dd>
          <dt>Broker</dt><dd>{bot.broker === "alpaca_paper" ? "Alpaca paper" : "Simulated"}</dd>
        </dl>
        {bot.prompt_version && (
          <>
            <div className="section-head" style={{ marginTop: 24 }}><h2>Desk Notes</h2></div>
            <dl className="dl">
              <dt>Prompt</dt><dd>{bot.prompt_version}</dd>
              <dt>Eval pass rate</dt><dd>{bot.eval ? `${(bot.eval.pass_rate * 100).toFixed(0)}% of ${bot.eval.scenarios}` : "—"}</dd>
              <dt>Calls today</dt><dd>{bot.budget ? `${bot.budget.calls_today} of ${bot.budget.max_calls}` : "—"}</dd>
            </dl>
          </>
        )}
        <div className="section-head" style={{ marginTop: 24 }}><h2>Open Positions</h2></div>
        {bot.positions.length ? (
          <div className="table-wrap"><table>
            <caption className="sr-only">Open positions</caption>
            <thead><tr><th scope="col">Symbol</th><th scope="col" className="num">Qty</th><th scope="col" className="num">Cost</th><th scope="col" className="num">Last</th><th scope="col" className="num">P&amp;L</th></tr></thead>
            <tbody>{bot.positions.map((p) => (
              <tr key={p.symbol}><th scope="row" className="mono">{p.symbol}</th><td className="num mono">{qty(p.qty)}</td><td className="num mono">{price(p.avg_cost)}</td>
                <td className="num mono">{price(p.last)}</td><td className={`num mono${p.pnl < 0 ? " down" : ""}`}>{p.pnl < 0 ? "▼" : "▲"}{dollars(Math.abs(p.pnl))}</td></tr>
            ))}</tbody></table></div>
        ) : <p className="deck">Flat. No open positions.</p>}
      </aside>
      <section className="col c-12" style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="section-head"><h2>Trade History</h2><span className="kicker">Newest first, refusals included</span></div>
        <Wire initial={trades.items} bot={bot.slug} />
      </section>
    </div>
  );
}
