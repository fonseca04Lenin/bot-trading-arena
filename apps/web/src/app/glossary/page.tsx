import type { Metadata } from "next";
import { ApiError, getGlossary } from "@/lib/api";

export const metadata: Metadata = { title: "Glossary" };
export const dynamic = "force-dynamic";

export default async function Glossary() {
  const entries = await getGlossary().catch((e) => (e instanceof ApiError ? null : null));
  return (
    <section className="col prose">
      <p className="kicker">Terms marked {"†"}</p>
      <h1 className="headline">Glossary</h1>
      {!entries ? <p className="deck">The glossary is at the printer. Try again in a moment.</p> : (
        <dl>
          {entries.map((e) => (
            <div key={e.term} id={e.term} style={{ padding: "12px 0", borderBottom: "1px solid var(--rule)" }}>
              <dt><h2 style={{ fontSize: "1.5rem" }}>{e.label}</h2></dt>
              <dd style={{ margin: "4px 0 0" }}>{e.definition}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
