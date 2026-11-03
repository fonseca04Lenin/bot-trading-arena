const ET = "America/New_York";

export function money(n: number, digits = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function dollars(n: number): string {
  return `$${money(n, 0)}`;
}

/** Signed percentage with a typographic arrow: gains in ink (▲), losses in spot (▼). */
export function pct(n: number | null | undefined, digits = 2): { text: string; down: boolean } {
  if (n === null || n === undefined || Number.isNaN(n)) return { text: "—", down: false };
  const v = Math.abs(n * 100).toFixed(digits);
  if (n < 0) return { text: `▼${v}%`, down: true };
  return { text: `▲${v}%`, down: false };
}

export function plainPct(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`;
}

export function ratio(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toFixed(2);
}

export function timeET(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" }) + " ET";
}

export function dateTimeET(iso: string): string {
  return (
    new Date(iso).toLocaleString("en-US", {
      timeZone: ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    }) + " ET"
  );
}

export function longDateET(d: Date = new Date()): string {
  return d.toLocaleDateString("en-US", { timeZone: ET, weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

export function qty(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: n < 1 ? 6 : 4 });
}

export function price(n: number): string {
  return n >= 1000 ? money(n, 0) : money(n, 2);
}
