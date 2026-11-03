// Usage: node e2e/screenshots.mjs  (needs the stack running). Writes docs/screenshots/*.png
import { chromium } from "@playwright/test";

const base = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const out = new URL("../../../docs/screenshots/", import.meta.url).pathname;
const browser = await chromium.launch();
for (const [name, width, height] of [["desktop", 1280, 1700], ["mobile", 375, 1800]]) {
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme });
    const page = await ctx.newPage();
    await page.goto(base, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${out}front-${name}-${scheme === "light" ? "day" : "night"}.png` });
    await ctx.close();
  }
}
await browser.close();
