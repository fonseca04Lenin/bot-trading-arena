import type { Silks as SilksT } from "@/lib/api";

const COLORS: Record<string, string> = {
  ink: "#231b16", paper: "#fbf3df", spot: "#e2552d",
  ochre: "#e8a921", slate: "#2b5fc7", olive: "#2f8a57", oxblood: "#7a3fb0",
};

export function Silks({ silks, size = 22, title }: { silks: SilksT; size?: number; title?: string }) {
  const [a, b] = silks.colors.map((c) => COLORS[c] ?? "var(--ink)");
  const shapes = {
    quartered: <><rect x="0" y="0" width="12" height="12" fill={b} /><rect x="12" y="12" width="12" height="12" fill={b} /></>,
    hooped: <><rect x="0" y="4" width="24" height="4" fill={b} /><rect x="0" y="12" width="24" height="4" fill={b} /><rect x="0" y="20" width="24" height="4" fill={b} /></>,
    chevron: <><path d="M0 8 L12 18 L24 8 L24 14 L12 24 L0 14Z" fill={b} /></>,
    diamonds: <><path d="M12 2 L18 8 L12 14 L6 8Z" fill={b} /><path d="M6 14 L12 20 L6 26 L0 20Z M18 14 L24 20 L18 26 L12 20Z" fill={b} /></>,
    sash: <path d="M0 0 L8 0 L24 16 L24 24 L16 24 L0 8Z" fill={b} />,
  } as Record<string, React.ReactNode>;
  return (
    <svg className="silks" width={size} height={size} viewBox="0 0 24 24" role={title ? "img" : undefined}
      aria-label={title} aria-hidden={title ? undefined : true}>
      <rect width="24" height="24" fill={a} />
      <g>{shapes[silks.pattern]}</g>
      <rect x="0.5" y="0.5" width="23" height="23" fill="none" stroke="#231b16" strokeWidth="1.5" />
    </svg>
  );
}
