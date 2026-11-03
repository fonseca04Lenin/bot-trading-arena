import { cache } from "react";
import type { components } from "./api-types";

export type BacktestRequest = components["schemas"]["BacktestRequest"];

export const API_URL = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Silks = { pattern: string; colors: [string, string] };

export type Bot = {
  slug: string;
  name: string;
  silks: Silks;
  broker: string;
  description: string;
  starting_cash: number;
  rank: number;
  equity: number;
  return: number;
  today: number | null;
  sharpe: number | null;
  max_drawdown: number;
  win_rate: number | null;
  trades: number;
  sparkline: number[];
};

export type Evidence = { metric: string; value: number };

export type Trade = {
  id: string;
  ts: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number | null;
  status: "submitted" | "filled" | "rejected" | "canceled";
  reject_reason: string | null;
  broker: string;
  latency_ms: number | null;
  bot_slug: string;
  bot_name: string;
  silks: Silks;
  rationale: string;
  evidence: Evidence[];
};

export type TickerItem = { symbol: string; price: number; change: number | null };
export type EquityPoint = { ts: string; equity: number };
export type Freshness = { last_update: string | null; stale: boolean };

export type FrontPage = {
  headline: string;
  deck: string;
  edition_no: number;
  market_open: boolean;
  freshness: Freshness;
  leaderboard: Bot[];
  trades: Trade[];
  ticker: TickerItem[];
  equity: Record<string, [string, number][]>;
  market_note: string | null;
};

export type Position = { symbol: string; qty: number; avg_cost: number; last: number; pnl: number };
export type EvalReport = { pass_rate: number; scenarios: number; passed: number; source: string; model: string };

export type BotDetail = Bot & {
  positions: Position[];
  prompt_version?: string;
  eval?: EvalReport | null;
  budget?: { calls_today: number; max_calls: number };
};

export type TradeDetail = Trade & { bars: { ts: string; o: number; h: number; l: number; c: number }[] };
export type GlossaryEntry = { term: string; label: string; definition: string };

export type Status = {
  services: { service: string; last_seen: string; healthy: boolean }[];
  uptime: { per_service: Record<string, number>; overall: number | null };
  p95_signal_to_submit_ms: number | null;
  total_orders: number;
  eval: EvalReport | null;
  freshness: Freshness;
};

export type BacktestResult = {
  equity: EquityPoint[];
  trades: { ts: string; side: string; qty: number; price: number; rationale: string }[];
  metrics: { return: number; max_drawdown: number; sharpe: number | null; win_rate: number | null; trades: number; bars: number };
};

export class ApiError extends Error {}

export async function get<T>(path: string, revalidate = 5): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { next: { revalidate } });
  } catch {
    throw new ApiError("The wire is down.");
  }
  if (!res.ok) throw new ApiError(`The API answered ${res.status}.`);
  return (await res.json()) as T;
}

export const getFrontPage = cache(() => get<FrontPage>("/api/front-page"));
export const getGlossary = cache(() => get<GlossaryEntry[]>("/api/glossary", 300));

export function toPoints(rows: [string, number][]): EquityPoint[] {
  return rows.map(([ts, equity]) => ({ ts, equity }));
}
