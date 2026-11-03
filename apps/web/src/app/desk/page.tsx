import type { Metadata } from "next";
import { Desk } from "@/components/Desk";

export const metadata: Metadata = { title: "The Handicapper's Desk" };

export default function DeskPage() {
  return (
    <section className="col">
      <p className="kicker">Try it yourself</p>
      <h1 className="headline">The Handicapper&rsquo;s Desk</h1>
      <p className="deck prose" style={{ marginBottom: 20 }}>
        How would The Breakout have done on NVDA over the past year? Pick a bot, a symbol and a window. The Desk replays
        daily bars through the same code the live bots run.
      </p>
      <Desk />
    </section>
  );
}
