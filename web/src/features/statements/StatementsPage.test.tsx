import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import { StatementsPage } from "./StatementsPage";

const summary = (over: Record<string, unknown> = {}) => ({
  statement_id: "stmt_1",
  bank: "santander_cl_cuentacorriente_xlsx",
  account_ref: "****3456",
  account_type: "checking",
  currency: "CLP",
  period_start: "2026-08-31",
  period_end: "2026-09-30",
  source: "xlsx",
  imported_at: "2026-10-15T20:00:00Z",
  line_count: 5,
  total_debits: 19869,
  total_credits: 66000,
  opening_balance: 100000,
  closing_balance: 146131,
  provisional: false,
  verified: true,
  issues: [],
  obligations: null,
  ...over,
});

const ok = (data: unknown, warnings: unknown[] = []) => ({ status: "OK", params_version: "st-0.1", facts: [], warnings, data });
const ready = (data: unknown) => ({ isPending: false, isError: false, data: ok(data), refetch: vi.fn() });

let importer: Record<string, unknown>;
const mutate = vi.fn();

vi.mock("@/api/hooks", () => ({
  usePersona: () => ({ persona: "camila", sessionId: "s" }),
  useStatements: () => ready([summary()]),
  useStatement: () => ready({ statement: summary(), lines: [], daily_balances: [] }),
  useTransactions: () =>
    ready({
      transactions: [
        {
          txn_id: "t1",
          account_id: "a",
          date: "2026-09-01",
          amount: -900,
          currency: "CLP",
          merchant: { untrusted_text: "<script>alert(1)</script> Transf a [PERSON]" },
          kind: "purchase",
          category: "uncategorized",
          classifier: "naive_bayes@x",
          confidence: 0.2,
          statement_id: "stmt_1",
          line_index: 0,
          installment: { plan_id: "p", installment_number: 2, installment_total: 12, original_amount: 12000, monthly_rate: null },
        },
      ],
      spending: [{ category: "uncategorized", currency: "CLP", spent: 900, count: 1 }],
      income: [],
    }),
  useImportStatement: () => importer,
}));

beforeEach(() => {
  mutate.mockReset();
  importer = { mutate, reset: vi.fn(), isPending: false, isError: false, error: null, data: undefined };
});

async function choose(file: File) {
  await userEvent.upload(screen.getByLabelText("Choose file"), file);
}

describe("StatementsPage", () => {
  it("lists statements with the currency code and says imports do not change projections", () => {
    render(<StatementsPage />);
    expect(screen.getByText(/Projections, the purchase check and the savings plan still use the demo scenario/)).toBeInTheDocument();
    expect(screen.getByText("CLP 146,131")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("uploads the chosen file and shows what was hidden and posted", async () => {
    const { rerender } = render(<StatementsPage />);
    const file = new File(["x"], "cartola.xlsx");
    await choose(file);
    expect(mutate).toHaveBeenCalledWith(file);

    importer = {
      ...importer,
      data: ok({
        imports: [
          {
            duplicate: false,
            statement: summary(),
            redaction: { rules: "pii-0.1", detector: "none", degraded: false, counts: { PERSON: 1, NUMBER: 2 } },
            ledger: { posted: 5, new: 5, uncategorized: 3, classifier: "naive_bayes@x" },
          },
        ],
      }),
    };
    rerender(<StatementsPage />);
    expect(screen.getByText("Personal data hidden: Name hidden ×1, Number hidden ×2")).toBeInTheDocument();
    expect(screen.getByText("5 transactions in the ledger, 5 new, 3 without a category")).toBeInTheDocument();
  });

  it("marks a duplicate neutrally and explains an unverified statement that was not posted", async () => {
    const { rerender } = render(<StatementsPage />);
    await choose(new File(["x"], "again.pdf"));
    importer = {
      ...importer,
      data: ok({
        imports: [
          { duplicate: true, statement: summary(), redaction: null, ledger: { posted: 5, new: 0, uncategorized: 3, classifier: "x" } },
          {
            duplicate: false,
            statement: summary({ statement_id: "stmt_2", verified: false }),
            redaction: { rules: "pii-0.1", detector: "none", degraded: true, counts: {} },
            ledger: { posted: 0, new: 0, uncategorized: 0, classifier: null },
          },
        ],
      }),
    };
    rerender(<StatementsPage />);
    expect(screen.getAllByText("Already imported")).toHaveLength(1);
    expect(screen.getAllByText("Not verified").length).toBeGreaterThan(0);
    expect(screen.getByText("Stored, but not added to the ledger")).toBeInTheDocument();
    expect(screen.getByText("Only the built-in redaction rules ran")).toBeInTheDocument();
  });

  it("refuses a file over 15 MB before uploading it", async () => {
    render(<StatementsPage />);
    const big = new File(["x"], "scan.pdf");
    Object.defineProperty(big, "size", { value: 16 * 1024 * 1024 });
    await choose(big);
    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("larger than 15 MB");
  });

  it("explains a 413 from the server in the same words", () => {
    importer = { ...importer, isError: true, error: new ApiError(413, { detail: "the file is larger than 15 MB" }) };
    render(<StatementsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("The file is larger than 15 MB");
  });

  it("shows merchant text as plain text, with placeholders as chips and cuotas as n of N", async () => {
    const { container } = render(<StatementsPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Transactions" }));
    const merchant = screen.getByRole("rowheader", { name: /Transf a/ });
    expect(merchant).toHaveTextContent("<script>alert(1)</script> Transf a Name hidden");
    expect(container.querySelector("script")).toBeNull();
    expect(merchant).toHaveTextContent("2 of 12");
    expect(screen.getByText("CLP −900")).toBeInTheDocument();
  });
});
