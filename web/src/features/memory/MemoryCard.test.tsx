import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import type { IncomeProposal } from "@/api/hooks";
import { MemoryCard } from "./MemoryCard";

type Mutation = { mutate: ReturnType<typeof vi.fn>; isPending: boolean; isError: boolean; isSuccess: boolean; error: unknown; data?: unknown };
const idle = (): Mutation => ({ mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null });
let confirm = idle();
let consent: { data?: { consent: string; consent_generation: number; memory_revision: number } } = {
  data: { consent: "granted", consent_generation: 1, memory_revision: 0 },
};
afterEach(() => {
  confirm = idle();
  consent = { data: { consent: "granted", consent_generation: 1, memory_revision: 0 } };
});

vi.mock("@/api/hooks", () => ({ useConfirmMemory: () => confirm, useMemoryConsent: () => consent, useMemoryCounters: () => consent.data ?? null }));

const proposal = (overrides: Partial<IncomeProposal> = {}): IncomeProposal => ({
  proposal_id: "prp_1", status: "READY", candidates: [1_200_000], effective_from: { pay_month: "2026-11", read_as: "next_occurrence" },
  needs_base: false, chain_id: "chn_1", expected_version: 1, currency: "CLP", ...overrides,
});
const dependency = { consent_generation: 1, memory_revision: 0 };
const card = () => screen.getByRole("form", { name: "Salary to remember" });

describe("MemoryCard", () => {
  it("prefills one amount, shows the pay month and says saving changes no projection", async () => {
    render(<MemoryCard proposal={proposal()} dependency={dependency} currency="CLP" />);
    expect(card()).toHaveTextContent("1,200,000");
    expect(within(card()).getByLabelText(/From the pay month/)).toHaveValue("2026-11");
    expect(card()).toHaveTextContent("never a past one");
    expect(card()).toHaveTextContent("it moves no money and does not change your projections");
    await userEvent.click(within(card()).getByRole("button", { name: "Save salary" }));
    expect(confirm.mutate).toHaveBeenCalledOnce();
    expect(confirm.mutate).toHaveBeenCalledWith({
      proposalId: "prp_1", salary_net: { amount: 1_200_000, net: true, effective_from: "2026-11" }, expected_version: 1,
    });
  });

  it("lets the user choose between candidates and never picks one for them", async () => {
    render(<MemoryCard proposal={proposal({ status: "CHOOSE_AMOUNT", candidates: [1_000_000, 1_300_000] })} dependency={dependency} currency="CLP" />);
    await userEvent.click(within(card()).getByRole("button", { name: "Save salary" }));
    expect(confirm.mutate).not.toHaveBeenCalled();  // nothing chosen: nothing sent
    expect(screen.getByRole("alert")).toHaveTextContent("Type a whole amount");
    await userEvent.click(within(card()).getByLabelText("CLP 1,300,000"));
    await userEvent.click(within(card()).getByRole("button", { name: "Save salary" }));
    expect(confirm.mutate.mock.calls[0]![0].salary_net.amount).toBe(1_300_000);
  });

  it("asks for the amount when the message had none, and for an optional base on a new chain", async () => {
    render(<MemoryCard proposal={proposal({ status: "ASK_AMOUNT", candidates: [], needs_base: true, chain_id: null, expected_version: 0 })} dependency={dependency} currency="CLP" />);
    await userEvent.type(within(card()).getByLabelText("Net salary (CLP)"), "1.250.000");
    await userEvent.type(within(card()).getByLabelText(/Previous net salary/), "1000000");
    const baseMonth = within(card()).getByLabelText("Paid since the pay month");
    await userEvent.type(baseMonth, "2026-06");
    await userEvent.click(within(card()).getByRole("button", { name: "Save salary" }));
    expect(confirm.mutate).toHaveBeenCalledWith({
      proposalId: "prp_1", salary_net: { amount: 1_250_000, net: true, effective_from: "2026-11" }, expected_version: 0,
      base: { amount: 1_000_000, net: true, effective_from: "2026-06" },
    });
  });

  it("refuses a boolean-like or out-of-range amount before sending", async () => {
    render(<MemoryCard proposal={proposal({ status: "ASK_AMOUNT", candidates: [] })} dependency={dependency} currency="CLP" />);
    await userEvent.type(within(card()).getByLabelText("Net salary (CLP)"), "100000001");
    await userEvent.click(within(card()).getByRole("button", { name: "Save salary" }));
    expect(confirm.mutate).not.toHaveBeenCalled();
  });

  it.each([
    ["PROPOSAL_STALE", 409, "expired or is out of date"],
    ["PROPOSAL_USED", 409, "already confirmed"],
    ["CONSENT_REQUIRED", 428, "Memory is off"],
    ["VERSION_CONFLICT", 409, "changed meanwhile"],
  ])("closes on %s and offers no second confirmation", (status, code, text) => {
    confirm = { ...idle(), isError: true, error: new ApiError(code, { status, message: "x" }) };
    render(<MemoryCard proposal={proposal()} dependency={dependency} currency="CLP" />);
    expect(card()).toHaveTextContent(text);
    expect(within(card()).queryByRole("button", { name: "Save salary" })).toBeNull();
  });

  it("is obsolete once the memory counters it was prepared under move", () => {
    consent = { data: { consent: "revoked", consent_generation: 2, memory_revision: 0 } };
    render(<MemoryCard proposal={proposal()} dependency={dependency} currency="CLP" />);
    expect(card()).toHaveTextContent("can no longer be confirmed");
    expect(within(card()).queryByRole("button", { name: "Save salary" })).toBeNull();
  });

  it("words the saved state by the derived evidence, never claiming more", () => {
    const view = (status: string) => ({ catalog_version: "mem-0.1", consent: "granted", items: [{ check: { status } }] });
    for (const [status, text] of [["declared", "do not show it yet"], ["verified", "checked against your statements"]] as const) {
      confirm = { ...idle(), isSuccess: true, data: view(status) };
      const { unmount } = render(<MemoryCard proposal={proposal()} dependency={dependency} currency="CLP" />);
      expect(screen.getByRole("status")).toHaveTextContent(text);
      expect(screen.getByRole("status")).toHaveTextContent("does not change your projections");
      unmount();
    }
  });

  it("disables the button while the confirmation is in flight", () => {
    confirm = { ...idle(), isPending: true };
    render(<MemoryCard proposal={proposal()} dependency={dependency} currency="CLP" />);
    expect(within(card()).getByRole("button", { name: /Save salary/ })).toBeDisabled();
  });
});
