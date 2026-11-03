"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PUBLIC_API_URL, type Trade } from "@/lib/api";

type LiveState = { prices: Record<string, number>; trades: Trade[]; tick: number; reconnects: number; connected: boolean };
const Ctx = createContext<LiveState>({ prices: {}, trades: [], tick: 0, reconnects: 0, connected: false });

export const useLive = () => useContext(Ctx);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ prices: {}, trades: [], tick: 0, reconnects: 0, connected: false });
  const attempts = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let everConnected = false;
    const url = PUBLIC_API_URL.replace(/^http/, "ws") + "/ws";

    const connect = () => {
      ws = new WebSocket(url);
      ws.onopen = () => {
        attempts.current = 0;
        ws?.send(JSON.stringify({ action: "subscribe", channels: ["trades", "equity", "ticker"] }));
        setState((s) => ({ ...s, connected: true, reconnects: everConnected ? s.reconnects + 1 : s.reconnects }));
        everConnected = true;
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data as string);
        if (msg.type === "trade_filled") setState((s) => ({ ...s, trades: [msg.trade as Trade, ...s.trades] }));
        else if (msg.type === "equity_tick") setState((s) => ({ ...s, tick: s.tick + 1 }));
        else if (msg.type === "price_tick") setState((s) => ({ ...s, prices: { ...s.prices, [msg.symbol]: msg.price } }));
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (closed) return;
        const delay = Math.min(30000, 1000 * 2 ** attempts.current++);
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const value = useMemo(() => state, [state]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
