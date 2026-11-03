import Link from "next/link";
import type { FrontPage } from "@/lib/api";
import { longDateET, timeET } from "@/lib/format";
import { ThemeToggle } from "./ThemeToggle";
import { Ticker } from "./Ticker";

const NAV = [["/", "Front Page"], ["/desk", "The Desk"], ["/colophon", "Colophon"], ["/glossary", "Glossary"]];

export function Masthead({ page }: { page: FrontPage | null }) {
  return (
    <header className="page">
      <div className="masthead">
        <p className="title"><Link href="/">The Arena Daily</Link></p>
        <div className="dateline">
          <span>VOL. 1</span>
          <span>NO. {page?.edition_no ?? 1}</span>
          <span>{longDateET()}</span>
          <span className={`pill ${page?.market_open ? "open" : "closed"}`}>
            {page?.market_open ? <>MARKET OPEN<span className="live-dot" aria-hidden="true" /></> : <>MARKET CLOSED<span className="closed-dot" aria-hidden="true" /></>}
          </span>
          <ThemeToggle />
        </div>
      </div>
      <nav className="nav" aria-label="Sections">
        {NAV.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
      </nav>
      <Ticker items={page?.ticker ?? []} />
      {(!page || page.freshness.stale) && (
        <p style={{ margin: "10px 0 0" }}>
          <span className="stamp">LATE EDITION</span>{" "}
          <span className="mono">
            Prices delayed; last update {page?.freshness.last_update ? timeET(page.freshness.last_update) : "unknown"}.
          </span>
        </p>
      )}
    </header>
  );
}
