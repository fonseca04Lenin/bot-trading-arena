"use client";

import { useState } from "react";
import { PUBLIC_API_URL, type BacktestRequest, type BacktestResult } from "@/lib/api";
import { dateTimeET, dollars, pct, plainPct, price, qty, ratio } from "@/lib/format";
import { EquityChart } from "./EquityChart";
import { Term } from "./Glossary";

const STRATEGIES: [BacktestRequest["strategy_slug"], string][] = [
  ["breakout", "The Breakout"], ["crossover", "The Crossover"], ["rubber-band", "The Rubber Band"], ["index", "The Index"], ["scorecard", "The Analyst"],
];
const SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "BTC/USD", "ETH/USD"];
const SILKS = { pattern: "hooped", colors: ["ink", "paper"] as [string, string] };

function isoDay(offsetDays: number) {
  return new Date(Date.now() + offsetDays * 86400000).toISOString().slice(0, 10);
}

export function Desk() {
  const [strategy, setStrategy] = useState<BacktestRequest["strategy_slug"]>("breakout");
  const [symbol, setSymbol] = useState("NVDA");
  const [start, setStart] = useState(isoDay(-365));
  const [end, setEnd] = useState(isoDay(0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [ran, setRan] = useState<string>("");

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: BacktestRequest = { strategy_slug: strategy, symbol, start: `${start}T00:00:00Z`, end: `${end}T23:59:59Z`, params: {} };
      const res = await fetch(`${PUBLIC_API_URL}/api/backtest`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.error?.message ?? json?.detail?.[0]?.msg ?? "The Desk could not run that.");
      setResult(json as BacktestResult);
      setRan(`${STRATEGIES.find((s) => s[0] === strategy)?.[1]} on ${symbol}, ${start} to ${end}`);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "The Desk could not run that.");
    } finally {
      setBusy(false);
    }
  };

  const m = result?.metrics;
  return (
    <>
      <form className="desk-form" onSubmit={run}>
        <div className="field"><label htmlFor="strategy">Bot</label>
          <select id="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)}>
            {STRATEGIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></div>
        <div className="field"><label htmlFor="symbol">Symbol</label>
          <select id="symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
          </select></div>
        <div className="field"><label htmlFor="start">From</label><input id="start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <div className="field"><label htmlFor="end">To</label><input id="end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
        <button className="btn" type="submit" disabled={busy}>{busy ? "Running…" : "Run the numbers"}</button>
      </form>
      {error && <p style={{ marginTop: 16 }}><span className="stamp">NO RESULT</span> <span className="mono">{error}</span></p>}
      {result && m && (
        <section aria-label="Backtest result" style={{ marginTop: 24 }}>
          <div className="section-head"><h2>{ran}</h2><span className="kicker">Daily bars, $100,000 start, 2 bp slippage</span></div>
          <EquityChart
            series={[{ slug: "bt", name: STRATEGIES.find((s) => s[0] === strategy)?.[1] ?? "Result", silks: SILKS, leader: true,
              points: result.equity.map((p) => ({ ts: p.ts, equity: p.equity })) }]}
            summary={`Backtest equity curve, ${pct(m.return).text} total return.`} />
          <dl className="dl" style={{ margin: "16px 0" }}>
            <dt>Return</dt><dd className={m.return < 0 ? "down" : undefined}>{pct(m.return).text}</dd>
            <dt><Term id="drawdown">Max drawdown</Term></dt><dd>{plainPct(m.max_drawdown)}</dd>
            <dt><Term id="sharpe">Sharpe</Term></dt><dd>{ratio(m.sharpe)}</dd>
            <dt><Term id="win-rate">Win rate</Term></dt><dd>{plainPct(m.win_rate, 0)}</dd>
            <dt>Trades</dt><dd>{m.trades} over {m.bars} bars</dd>
          </dl>
          {result.trades.length > 0 ? (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Simulated trades</caption>
                <thead><tr><th scope="col">When</th><th scope="col">Side</th><th scope="col" className="num">Qty</th><th scope="col" className="num">Price</th><th scope="col">Reason</th></tr></thead>
                <tbody>{result.trades.map((t) => (
                  <tr key={t.ts + t.side}><td className="mono">{dateTimeET(t.ts)}</td><td className="mono">{t.side}</td>
                    <td className="num mono">{qty(t.qty)}</td><td className="num mono">{price(t.price)}</td><td>{t.rationale}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <p className="deck">No trades: the rule never fired in that window. Final equity {dollars(100000 * (1 + m.return))}.</p>}
        </section>
      )}
    </>
  );
}
