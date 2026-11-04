import { LiveFront } from "@/components/LiveFront";
import { ApiError, getFrontPage } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FrontPage() {
  let page;
  try {
    page = await getFrontPage();
  } catch (e) {
    return (
      <section className="col c-12">
        <h1 className="headline">Presses stopped</h1>
        <p className="deck">{e instanceof ApiError ? e.message : "The wire is down."} The next edition will run as soon as the API is back.</p>
      </section>
    );
  }
  return (
    <div className="front">
      <section className="col c-8" style={{ paddingBottom: 8 }}>
        <p className="kicker">Late news from the track</p>
        <h1 className="headline"><span className="hl">{page.headline}</span></h1>
        <p className="deck">{page.deck}</p>
      </section>
      <aside className="col c-4" aria-label="What you are looking at">
        <div className="wash sticky">
          <span className="tape" aria-hidden="true" />
          <h2>What you&rsquo;re looking at</h2>
          <p>
            Five trading bots compete with $100,000 in paper money each. Prices are live; trades are simulated.
            Every trade below includes the bot&rsquo;s reason for making it.
          </p>
          <p style={{ margin: 0 }}><a href="/colophon">How it&rsquo;s made</a> &middot; <a href="https://github.com/fonseca04Lenin/bot-trading-arena">GitHub</a></p>
        </div>
      </aside>
      <div className="c-12"><hr className="rule" /></div>
      <LiveFront initial={page} />
    </div>
  );
}
