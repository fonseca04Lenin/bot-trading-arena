import type { Bot } from "@/lib/api";
import { pct, plainPct, ratio } from "@/lib/format";
import { botInk } from "@/lib/colors";
import { Silks } from "./Silks";
import { Sparkline } from "./Sparkline";
import { Term } from "./Glossary";

function Change({ v, circled }: { v: number | null; circled?: boolean }) {
  const p = pct(v);
  return (
    <span className={`chip ${v === null ? "" : p.down ? "dn" : "up"}`}>
      {p.text}
      {circled && (
        <svg className="scribble" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
          <path d="M8 22 C 6 6, 60 2, 90 9 C 104 15, 94 34, 52 36 C 20 38, 2 30, 10 14 C 14 8, 30 5, 44 4" fill="none" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      )}
    </span>
  );
}

export function TheForm({ bots }: { bots: Bot[] }) {
  return (
    <>
      <div className="table-wrap">
        <table className="form-table">
          <caption className="sr-only">The Form: six bots ranked by return since launch</caption>
          <thead>
            <tr>
              <th scope="col">#</th><th scope="col"><span className="sr-only">Silks</span></th><th scope="col">Bot</th>
              <th scope="col" className="num">Return</th><th scope="col" className="num">Today</th>
              <th scope="col" className="num"><Term id="sharpe">Sharpe</Term></th>
              <th scope="col" className="num"><Term id="drawdown">Max DD</Term></th>
              <th scope="col" className="num"><Term id="win-rate">Win rate</Term></th>
              <th scope="col" className="num">Trades</th><th scope="col">30 days</th>
            </tr>
          </thead>
          <tbody>
            {bots.map((b) => (
              <tr key={b.slug} style={{ "--c": botInk(b.slug) } as React.CSSProperties}>
                <th scope="row" className="rank">{b.rank}</th>
                <td><Silks silks={b.silks} /></td>
                <td className="name"><a href={`/bots/${b.slug}`}>{b.name}</a></td>
                                <td className="num mono"><Change v={b.return} circled={b.rank === 1} /></td>
                <td className="num mono"><Change v={b.today} /></td>
                <td className="num mono">{ratio(b.sharpe)}</td>
                <td className="num mono">{plainPct(b.max_drawdown)}</td>
                <td className="num mono">{plainPct(b.win_rate, 0)}</td>
                <td className="num mono">{b.trades}</td>
                <td><Sparkline values={b.sparkline} label={`${b.name}, last 30 days`} color={botInk(b.slug)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ol className="form-list" aria-label="The Form, stacked for small screens">
        {bots.map((b) => (
          <li key={b.slug} style={{ "--c": botInk(b.slug) } as React.CSSProperties}>
            <div className="l1">
              <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ fontFamily: "var(--font-display)", fontSize: "1.8rem", lineHeight: 1, color: "var(--c)" }}>{b.rank}</span>
                <Silks silks={b.silks} />
                <a href={`/bots/${b.slug}`}><strong>{b.name}</strong></a>
              </span>
              <span className="mono"><Change v={b.return} /></span>
            </div>
            <div className="l2">
              <span>Today <Change v={b.today} /></span><span>Sharpe {ratio(b.sharpe)}</span>
              <span>DD {plainPct(b.max_drawdown)}</span><span>Win {plainPct(b.win_rate, 0)}</span><span>{b.trades} trades</span>
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}
