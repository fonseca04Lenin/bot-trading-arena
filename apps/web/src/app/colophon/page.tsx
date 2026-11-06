import type { Metadata } from "next";
import { Fragment } from "react";
import { Arch } from "@/components/Arch";
import { ApiError, get, type Status } from "@/lib/api";
import { plainPct, timeET } from "@/lib/format";

export const metadata: Metadata = { title: "Colophon" };
export const dynamic = "force-dynamic";

const STACK = [
  ["Web", "Next.js (App Router), TypeScript, hand-drawn SVG charts with D3 scales"],
  ["API", "Python 3.12, FastAPI, psycopg 3, WebSockets over Postgres LISTEN/NOTIFY"],
  ["Workers", "Python: ingest, six rule strategies, and scorer"],
  ["Execution", "Rust, Axum, Tokio, sqlx; idempotent orders, risk rules, sim and Alpaca paper brokers"],
  ["Data", "PostgreSQL 16 with plain SQL migrations"],
  ["Checks", "pytest, cargo test, vitest, Playwright; GitHub Actions on every push"],
];

export default async function Colophon() {
  const status = await get<Status>("/api/status", 10).catch((e) => (e instanceof ApiError ? null : null));
  return (
    <div className="front">
      <section className="col c-12">
        <p className="kicker">How it&rsquo;s made</p>
        <h1 className="headline">Colophon</h1>
        <p className="prose">
          Six bots trade paper money against live prices, and all six follow fixed rules. Only The Crossover routes orders to a real broker&rsquo;s paper-trading account; the others
          are simulated against the same prices.
        </p>
      </section>
      <section className="col c-12" style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="section-head"><h2>The Plant</h2></div>
        <Arch />
      </section>
      <section className="col c-6" style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="section-head"><h2>Typeset in</h2></div>
        <dl className="dl">{STACK.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd style={{ fontFamily: "var(--font-body)" }}>{v}</dd></Fragment>)}</dl>
      </section>
      <section className="col c-6" style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="section-head"><h2>Live Status</h2></div>
        {!status ? <p><span className="stamp">LATE EDITION</span> <span className="mono">Status is unavailable right now.</span></p> : (
          <>
            <dl className="dl">
              <dt>Uptime, 30 days</dt><dd>{status.uptime.overall === null ? "—" : plainPct(status.uptime.overall, 2)}</dd>
              <dt>p95 signal to submit</dt><dd>{status.p95_signal_to_submit_ms === null ? "—" : `${Math.round(status.p95_signal_to_submit_ms)} ms`}</dd>
              <dt>Orders processed</dt><dd>{status.total_orders}</dd>
            </dl>
            <table style={{ marginTop: 14 }}>
              <caption className="sr-only">Service heartbeats</caption>
              <thead><tr><th scope="col">Service</th><th scope="col">Last seen</th><th scope="col">State</th></tr></thead>
              <tbody>{status.services.map((s) => (
                <tr key={s.service}><th scope="row" className="mono">{s.service}</th><td className="mono">{timeET(s.last_seen)}</td>
                  <td className={s.healthy ? undefined : "down"}>{s.healthy ? "up" : "stale"}</td></tr>
              ))}</tbody>
            </table>
          </>
        )}
        <p style={{ marginTop: 16 }}>
          Built by <a href="https://elvinfonseca.com">Elvin Fonseca</a> &middot; <a href="https://github.com/fonseca04Lenin/bot-trading-arena">Source on GitHub</a>
        </p>
      </section>
    </div>
  );
}
