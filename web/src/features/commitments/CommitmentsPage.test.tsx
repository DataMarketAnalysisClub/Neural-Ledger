import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CommitmentsPage } from "./CommitmentsPage";

// Labels come from merchant text, so a rent paid by transfer can carry a placeholder once statements feed the forecast.
vi.mock("@/api/hooks", () => {
  const ready = (data: unknown) => ({ isPending: false, isError: false, data: { data, facts: [] } });
  return {
    useCommitments: () =>
      ready({
        horizon_months: 6,
        commitments: [
          { commitment_id: "rent", type: "rent", label: { untrusted_text: "Transf a [PERSON]" }, amount: 450000, first_due: "2026-11", last_due: null, is_debt: false },
          { commitment_id: "phone", type: "installment", label: { untrusted_text: "Compra Nacional MD PHONE STORE" }, amount: 38995, first_due: "2026-11", last_due: "2027-10", is_debt: true },
        ],
        schedule: [{ month: "2026-11", total: 488995, debt: 38995 }],
      }),
    useCapacity: () => ready({ factors: [] }),
    useFinancialState: () => ready({ currency: "CLP" }),
  };
});

describe("CommitmentsPage", () => {
  it("shows placeholders in commitment labels as translated chips, never as raw codes", () => {
    const { container } = render(<CommitmentsPage />);
    const rent = screen.getByRole("rowheader", { name: /Transf a/ });
    expect(rent).toHaveTextContent("Transf a Name hidden");
    expect(rent.querySelector("[data-placeholder='PERSON']")).not.toBeNull();
    expect(rent.querySelector("[title]")).toHaveAttribute("title", "Transf a [Name hidden]");
    expect(screen.getByRole("rowheader", { name: "Compra Nacional MD PHONE STORE" })).toBeInTheDocument();
    expect(container.textContent).not.toContain("[PERSON]");
  });
});
