import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Silks } from "@/components/Silks";
import { TradeChart } from "@/components/TradeChart";
import { ApiError, get, type TradeDetail } from "@/lib/api";
import { dateTimeET, price, qty } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Trade Report" };

export default async function TradePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let t: TradeDetail;
  try {
    t = await get<TradeDetail>(`/api/trades/${id}`, 30);
  } catch (e) {
    if (e instanceof ApiError && e.message.endsWith("404.")) notFound();
    return <section className="col"><h1 className="headline">Report unavailable</h1><p className="deck">{e instanceof Error ? e.message : "The wire is down."}</p></section>;
  }
  const verb = t.side === "BUY" ? "Bought" : "Sold";
  return (
    <div className="front">
      <section className="col c-8">
        <p className="kicker">Trade Report &middot; {dateTimeET(t.ts)}</p>
        <h1 className="headline">{t.status === "rejected" ? "Scratched" : verb} {qty(t.qty)} {t.symbol}</h1>
        <p className="deck" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Silks silks={t.silks} size={22} /> <a href={`/bots/${t.bot_slug}`}>{t.bot_name}</a>
        </p>
        <p className="prose" style={{ marginTop: 16, fontSize: "1.15rem" }}>{t.rationale}</p>
        {t.status === "rejected" && <p><span className="stamp">SCRATCHED</span> <span className="mono">{t.reject_reason}</span></p>}
        <TradeChart trade={t} />
      </section>
      <aside className="col c-4">
        <div className="section-head"><h2>Evidence</h2></div>
        {t.evidence.length ? (
          <table><caption className="sr-only">Numbers the bot cited</caption>
            <thead><tr><th scope="col">Metric</th><th scope="col" className="num">Value</th></tr></thead>
            <tbody>{t.evidence.map((e) => <tr key={e.metric}><th scope="row" className="mono">{e.metric}</th><td className="num mono">{e.value}</td></tr>)}</tbody></table>
        ) : <p className="deck">This bot cites no figures beyond the rationale.</p>}
        <div className="section-head" style={{ marginTop: 24 }}><h2>The Order</h2></div>
        <dl className="dl">
          <dt>Status</dt><dd>{t.status}</dd>
          <dt>Fill</dt><dd>{t.price ? price(t.price) : "—"}</dd>
          <dt>Broker</dt><dd>{t.broker === "alpaca_paper" ? "Alpaca paper" : "Simulated"}</dd>
          <dt>Signal to submit</dt><dd>{t.latency_ms === null ? "—" : `${t.latency_ms} ms`}</dd>
        </dl>
      </aside>
    </div>
  );
}
