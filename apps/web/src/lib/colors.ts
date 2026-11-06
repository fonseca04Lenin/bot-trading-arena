/** One ink per bot, used for chart lines, rank numerals, the Wire's margin strip and silks. */
export const BOT_INK: Record<string, string> = {
  index: "#2f8a57",
  analyst: "#7a3fb0",
  crossover: "#e2552d",
  breakout: "#2b5fc7",
  "rubber-band": "#e8a921",
  quant: "#1f9d9d",
  orb: "#c2417a",
};

export const botInk = (slug: string) => BOT_INK[slug] ?? "var(--ink)";
