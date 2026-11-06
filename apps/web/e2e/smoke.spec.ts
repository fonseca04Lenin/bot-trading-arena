import { expect, test } from "@playwright/test";

test("front page renders the Form with six bots", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The Form" })).toBeVisible();
  await expect(page.locator("table.form-table tbody tr")).toHaveCount(6);
  await expect(page.getByText("What you’re looking at")).toBeVisible();
});

test("a bot page loads with its chart and history", async ({ page }) => {
  await page.goto("/bots/breakout");
  await expect(page.getByRole("heading", { name: "The Breakout", level: 1 })).toBeVisible();
  await expect(page.locator("svg.chart").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Trade History" })).toBeVisible();
});

test("the Desk returns a chart", async ({ page }) => {
  await page.goto("/desk");
  await page.getByRole("button", { name: "Run the numbers" }).click();
  await expect(page.getByLabel("Backtest result")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("section[aria-label='Backtest result'] svg.chart")).toBeVisible();
});

test("the Night edition toggle works and is remembered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Switch between Day and Night/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
});

for (const path of ["/", "/bots/analyst", "/desk", "/colophon", "/glossary"]) {
  test(`no horizontal scroll at 375px on ${path}`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(path);
    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    expect(sw).toBeLessThanOrEqual(cw);
  });
}
