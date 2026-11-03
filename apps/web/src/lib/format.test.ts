import { describe, expect, it } from "vitest";
import { dollars, money, pct, plainPct, price, qty, ratio, timeET } from "./format";

describe("format", () => {
  it("formats money with grouping", () => {
    expect(money(1234.5)).toBe("1,234.50");
    expect(dollars(100000)).toBe("$100,000");
  });
  it("marks gains with a up arrow and losses with a down arrow", () => {
    expect(pct(0.0123)).toEqual({ text: "▲0.01%".replace("0.01", "1.23"), down: false });
    expect(pct(-0.05)).toEqual({ text: "▼5.00%", down: true });
    expect(pct(null).text).toBe("—");
  });
  it("renders missing values as an em dash", () => {
    expect(ratio(null)).toBe("—");
    expect(plainPct(undefined)).toBe("—");
    expect(ratio(1.234)).toBe("1.23");
    expect(plainPct(0.5)).toBe("50.0%");
  });
  it("shows Eastern time", () => {
    expect(timeET("2026-01-05T15:00:00Z")).toBe("10:00 AM ET");
  });
  it("formats quantities and prices", () => {
    expect(qty(99.98)).toBe("99.98");
    expect(price(97410.2)).toBe("97,410");
    expect(price(231.4)).toBe("231.40");
  });
});
