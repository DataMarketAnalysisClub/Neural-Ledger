import { describe, expect, it } from "vitest";
import { formatAmount, formatMoney, formatMonth, formatPercent, moneyForSpeech, shortHash } from "./format";

describe("formatMoney", () => {
  it("always shows the ISO code before the amount", () => {
    expect(formatMoney(1_500_000, "CLP")).toBe("CLP 1,500,000");
    expect(formatMoney(20_000, "CLP")).toBe("CLP 20,000");
  });

  it("uses a real minus sign for negatives", () => {
    expect(formatMoney(-18_995, "CLP")).toBe("CLP −18,995");
  });

  it("signs positive flows only when asked", () => {
    expect(formatMoney(260_000, "CLP", { signed: true })).toBe("CLP +260,000");
    expect(formatMoney(260_000, "CLP")).toBe("CLP 260,000");
  });

  it("shifts minor units by the currency's own decimals, for any currency", () => {
    expect(formatMoney(1250, "USD")).toBe("USD 12.50");
    expect(formatMoney(1250, "EUR")).toBe("EUR 12.50");
    expect(formatMoney(1250, "JPY")).toBe("JPY 1,250");
  });

  it("formatAmount drops only the code", () => {
    expect(formatAmount(-660_000, "CLP")).toBe("−660,000");
  });

  it("speaks negatives as words", () => {
    expect(moneyForSpeech(-18_995, "CLP")).toBe("minus CLP 18,995");
  });
});

describe("other formats", () => {
  it("months always carry the year", () => {
    expect(formatMonth("2026-12")).toBe("Dec 2026");
    expect(formatMonth("2027-09", "long")).toBe("September 2027");
  });

  it("ratios become percentages", () => {
    expect(formatPercent(0.219444)).toBe("21.9%");
    expect(formatPercent(0.344889)).toBe("34.5%");
  });

  it("hashes are truncated with an ellipsis", () => {
    expect(shortHash("d3123c8d9f81e398d08003ab8d6988b7")).toBe("d3123c…88b7");
  });
});
