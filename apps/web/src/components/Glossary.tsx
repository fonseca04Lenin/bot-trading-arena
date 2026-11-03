"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { GlossaryEntry } from "@/lib/api";

const Ctx = createContext<Record<string, GlossaryEntry>>({});

export function GlossaryProvider({ entries, children }: { entries: GlossaryEntry[]; children: ReactNode }) {
  return <Ctx.Provider value={Object.fromEntries(entries.map((e) => [e.term, e]))}>{children}</Ctx.Provider>;
}

/** A finance term with a dagger footnote: hover or focus shows the one-sentence definition. */
export function Term({ id, children }: { id: string; children: ReactNode }) {
  const entry = useContext(Ctx)[id];
  return (
    <span className="fn">
      <a href={`/glossary#${id}`}>{children}<sup>{"†"}</sup></a>
      {entry && <span className="def" role="tooltip">{entry.definition}</span>}
    </span>
  );
}
