import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { axe } from "vitest-axe";
import { PersonaProvider } from "@/api/hooks";
import { ProposalReceipt, VerdictBanner } from "./actions";

const terms = {
  action: "create_savings_rule",
  amount: 100000,
  currency: "CLP",
  frequency: "monthly",
  source_account: "checking",
  destination: "sandbox_savings",
  effective_date: "2027-01-01",
} as const;

const proposal = {
  proposal_id: "prop_000014",
  session_id: "s1",
  user_id: "camila",
  terms,
  source_snapshot_id: "plan_52ae8e291e50e6a4",
  created_at: "2026-10-29T12:00:00-03:00",
  expires_at: "2099-10-29T12:30:00-03:00",
  status: "pending",
};

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PersonaProvider>{ui}</PersonaProvider>
    </QueryClientProvider>,
  );
}

describe("ProposalReceipt", () => {
  it("sends back the exact proposal it received, untouched", async () => {
    const onConfirm = vi.fn();
    wrap(<ProposalReceipt proposal={proposal as never} onConfirm={onConfirm} onExecute={vi.fn()} confirming={false} executing={false} />);
    await userEvent.click(screen.getByRole("button", { name: /Confirm CLP 100,000 monthly/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]![0]).toBe(proposal);
    expect(onConfirm.mock.calls[0]![0].terms).toBe(terms);
  });

  it("offers no way to edit the terms", () => {
    wrap(<ProposalReceipt proposal={proposal as never} onConfirm={vi.fn()} onExecute={vi.fn()} confirming={false} executing={false} />);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(screen.queryAllByRole("spinbutton")).toHaveLength(0);
  });

  it("disables confirmation while the request is in flight (no double submit)", () => {
    wrap(<ProposalReceipt proposal={proposal as never} onConfirm={vi.fn()} onExecute={vi.fn()} confirming executing={false} />);
    expect(screen.getByRole("button", { name: /Confirm/ })).toBeDisabled();
  });

  it("shows execution as a separate step only after confirmation", () => {
    const authorization = { authorization_id: "auth_1", proposal_id: "prop_000014", terms, expires_at: "2099-10-29T12:10:00-03:00", used: false };
    wrap(
      <ProposalReceipt
        proposal={proposal as never}
        authorization={authorization as never}
        onConfirm={vi.fn()}
        onExecute={vi.fn()}
        confirming={false}
        executing={false}
      />,
    );
    expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Create the CLP 100,000 rule in sandbox/ })).toBeEnabled();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = wrap(<ProposalReceipt proposal={proposal as never} onConfirm={vi.fn()} onExecute={vi.fn()} confirming={false} executing={false} />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("VerdictBanner", () => {
  it("states the refusal, both amounts and that nothing changed", () => {
    render(<VerdictBanner reason="AUTHORIZATION_MISMATCH" currency="CLP" authorized={100000} requested={700000} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The request does not match what you authorized.");
    expect(screen.getByText("CLP 100,000")).toBeInTheDocument();
    expect(screen.getAllByText("CLP 700,000").length).toBeGreaterThan(0);
    expect(screen.getByText("Nothing changed. The attempt was recorded.")).toBeInTheDocument();
  });

  it("falls back to a generic reason for unknown codes", () => {
    render(<VerdictBanner reason="SOMETHING_NEW" currency="CLP" />);
    expect(screen.getByRole("alert")).toHaveTextContent("The action was refused.");
  });
});
