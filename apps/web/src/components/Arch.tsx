type Box = { x: number; y: number; w: number; label: string; sub: string };

const BOXES: Box[] = [
  { x: 10, y: 20, w: 150, label: "Alpaca data", sub: "stocks + crypto" },
  { x: 200, y: 20, w: 150, label: "Ingest", sub: "Python, 5-min bars" },
  { x: 200, y: 130, w: 150, label: "Postgres", sub: "bars, orders, fills" },
  { x: 390, y: 20, w: 170, label: "Strategy workers", sub: "5 rule bots" },
  { x: 600, y: 55, w: 160, label: "Execution", sub: "Rust, Axum" },
  { x: 600, y: 160, w: 160, label: "Alpaca paper", sub: "Crossover only" },
  { x: 390, y: 200, w: 170, label: "Scorer", sub: "equity, metrics" },
  { x: 200, y: 240, w: 150, label: "API + WebSocket", sub: "FastAPI" },
  { x: 10, y: 240, w: 150, label: "Web", sub: "Next.js on Vercel" },
];

const EDGES: [number, number, number, number][] = [
  [160, 45, 200, 45], [275, 70, 275, 130], [350, 45, 390, 45], [560, 45, 600, 75],
  [680, 105, 680, 160], [600, 90, 350, 150], [390, 222, 350, 160], [275, 188, 275, 240], [200, 265, 160, 265],
];

export function Arch() {
  return (
    <svg className="arch chart" viewBox="0 0 780 310" role="img"
      aria-label="Architecture: market data feeds an ingest worker into Postgres. Strategy workers send signals to a Rust execution service, which fills against Postgres or Alpaca's paper API. A scorer and a FastAPI gateway read Postgres and feed the web app.">
      {EDGES.map(([x1, y1, x2, y2], i) => <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ink)" strokeWidth="1" />)}
      {BOXES.map((b) => (
        <g key={b.label}>
          <rect x={b.x} y={b.y} width={b.w} height={50} fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
          <text className="cap" x={b.x + 8} y={b.y + 21}>{b.label}</text>
          <text x={b.x + 8} y={b.y + 39}>{b.sub}</text>
        </g>
      ))}
    </svg>
  );
}
