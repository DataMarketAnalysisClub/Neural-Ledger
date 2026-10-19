import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SpendingToday } from "./SpendingToday";
import { tDynamic } from "@/i18n";

const check = (over: Record<string, unknown> = {}) => ({
  cycle: "2026-10",
  window_start: "2026-09-30",
  window_end: "2026-10-29",
  projected: false,
  today: "2026-10-19",
  days_left: 11,
  assumed: 900000,
  logged: 12990,
  logged_items: 1,
  left: 887010,
  per_day: 80637,
  overspend: 0,
  protected_surplus: 20000,
  surplus_after: 20000,
  categories: [{ category: "groceries", assumed: 330000, logged: 12990 }, { category: "uncategorized", assumed: 0, logged: 13720 }],
  ...over,
});
let spending: { data?: unknown } = {};
afterEach(() => { spending = {}; });

vi.mock("@/api/hooks", () => ({ useSpending: () => spending }));

const envelope = (c: Record<string, unknown>) => ({
  data: {
    status: "OK",
    params_version: "fc-0.3",
    snapshot_id: "spending_1",
    facts: [{ key: "spending.per_day", value: c.per_day, unit: "CLP", derivation: "left // days left" }],
    warnings: [],
    data: { check: c, latest_receipt: null, receipts_counted: 1, receipts_matched: 0 },
  },
});

describe("SpendingToday", () => {
  it("shows the API's daily figure, the days to payday, what is logged and each category", () => {
    spending = envelope(check());
    render(<MemoryRouter><SpendingToday currency="CLP" /></MemoryRouter>);
    const card = screen.getByRole("region", { name: "You can spend today" });
    expect(card).toHaveTextContent(/80.637/);
    expect(card).toHaveTextContent("for 11 days, until payday on");
    expect(screen.getByRole("img", { name: /12.990 of .*900.000 logged this pay cycle/ })).toBeInTheDocument();
    expect(card).toHaveTextContent(/887.010 left/);
    expect(card).toHaveTextContent("Groceries");
    expect(screen.getAllByRole("img", { name: /Groceries|Uncategorized/ })).toHaveLength(1); // no budget, no bar to fill
    expect(card).toHaveTextContent(/Uncategorized.*13.720/);
    expect(screen.getByRole("link", { name: "Add a receipt" })).toHaveAttribute("href", "/copilot");
  });

  it("says by how much spending passed the forecast", () => {
    spending = envelope(check({ logged: 905000, left: -5000, per_day: 0, overspend: 5000 }));
    render(<MemoryRouter><SpendingToday currency="CLP" /></MemoryRouter>);
    expect(screen.getByRole("region", { name: "You can spend today" })).toHaveTextContent(/5.000 over what the forecast counts on/);
  });

  it("stays out of the way without a financial model", () => {
    spending = { data: undefined };
    const { container } = render(<MemoryRouter><SpendingToday currency="CLP" /></MemoryRouter>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("audit labels for imports", () => {
  it("name every import event in words", () => {
    expect(["STATEMENT_IMPORTED", "DOCUMENT_ROUTED", "RECEIPT_IMPORTED"].map((k) => tDynamic("audit.kinds", k))).toEqual([
      "Statement imported",
      "Document recognized",
      "Receipt imported",
    ]);
  });
});
