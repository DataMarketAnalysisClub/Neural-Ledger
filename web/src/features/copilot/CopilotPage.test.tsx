import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CopilotPage } from "./CopilotPage";

let sessionId = "ui-camila-first";
const newSession = vi.fn(() => {
  sessionId = "ui-camila-second";
});
const idle = () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, error: null });
let chat: ReturnType<typeof idle> = idle();
let ingest: ReturnType<typeof idle> = idle();
let correction: ReturnType<typeof idle> = idle();
let expenseConfirm: ReturnType<typeof idle> & { isSuccess?: boolean } = idle();
let counters: { consent_generation: number; memory_revision: number } | null = null; // what the tab knows (useMemoryCounters)
afterEach(() => { chat = idle(); ingest = idle(); correction = idle(); expenseConfirm = idle(); counters = null; vi.useRealTimers(); });

vi.mock("@/api/hooks", () => ({
  usePersona: () => ({ persona: "camila", sessionId, newSession }),
  useFinancialState: () => ({ data: undefined }),
  usePending: () => ({ data: undefined }),
  useHealth: () => ({ data: undefined }),
  useChat: () => chat,
  useConfirmProposal: () => idle(),
  useExecute: () => idle(),
  useIngestDocument: () => ingest,
  useCorrectReceipt: () => correction,
  useConfirmExpense: () => expenseConfirm,
  useConfirmMemory: () => idle(),
  useMemoryConsent: () => ({ data: undefined }),
  useMemoryCounters: () => counters,
}));

describe("CopilotPage", () => {
  it("New conversation asks for a new session and starts from an empty log", async () => {
    const { rerender } = render(
      <MemoryRouter>
        <CopilotPage />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Will I be OK in December?" }));
    expect(screen.getByRole("log")).toHaveTextContent("Will I be OK in December?");

    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(newSession).toHaveBeenCalledOnce();
    rerender(
      <MemoryRouter>
        <CopilotPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("log")).not.toHaveTextContent("Will I be OK in December?");
    expect(screen.getByRole("log")).toHaveTextContent("Ask a question about your cash flow");
  });

  it("shows the avatar thinking while the engine is consulted", () => {
    chat = { ...idle(), isPending: true };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const thinking = screen.getByRole("status");
    expect(thinking.querySelector("svg")).toHaveAttribute("data-state", "thinking");
  });

  it("has the avatar answer, then rest, and keeps earlier replies still", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const reply = { text: "Not comfortably.", actions: [], tools_called: [], facts: [], warnings: [], blocked_reason: null, fallback_used: false, verification: { ok: true } };
    chat = { ...idle(), mutate: vi.fn((_message: string, options?: { onSuccess?: (r: unknown) => void }) => options?.onSuccess?.(reply)) };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    await user.click(screen.getByRole("button", { name: "Will I be OK in December?" }));
    const avatars = () => [...screen.getByRole("log").querySelectorAll("svg[data-state]")];
    expect(avatars().at(-1)).toHaveAttribute("data-state", "responding");

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(avatars().at(-1)).toHaveAttribute("data-state", "idle");
    await user.click(screen.getByRole("button", { name: "Just make it work." }));
    expect(avatars().filter((a) => a.getAttribute("data-still") === "true")).toHaveLength(1);
  });

  it("puts the avatar to the left of the reply, like a messaging app", async () => {
    const reply = { text: "Not comfortably.", actions: [], tools_called: [], facts: [], warnings: [], blocked_reason: null, fallback_used: false, verification: { ok: true } };
    chat = { ...idle(), mutate: vi.fn((_message: string, options?: { onSuccess?: (r: unknown) => void }) => options?.onSuccess?.(reply)) };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Will I be OK in December?" }));

    const avatar = screen.getByRole("log").querySelector("svg[data-state]")!;
    const row = avatar.parentElement!;
    expect(row.firstElementChild).toBe(avatar);
    expect(row).toHaveTextContent("Not comfortably.");
    expect(avatar).toHaveAttribute("data-shape", "round");
  });

  it("sends on Enter on a wide screen", async () => {
    const mutate = vi.fn();
    chat = { ...idle(), mutate };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Ask about your money"), "hello{Enter}");
    expect(mutate).toHaveBeenCalledWith("hello", expect.anything());
  });

  it("keeps the savings-rule panel on a wide screen", () => {
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    expect(screen.getByText("Savings rule")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Suggested questions" })).toBeInTheDocument();
  });

  describe("on a phone", () => {
    function phone() {
      vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width: 1023px"), media: query, addEventListener() {}, removeEventListener() {} }));
      return render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    }
    afterEach(() => vi.unstubAllGlobals());

    it("opens the back camera to photograph a receipt and shows the photo it sends", async () => {
      vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:receipt"), revokeObjectURL: vi.fn() }));
      ingest = { ...idle(), mutate: vi.fn() };
      phone();
      const camera = screen.getByLabelText("Take a photo of a receipt", { selector: "input" });
      expect(camera).toHaveAttribute("capture", "environment");
      expect(camera).toHaveAttribute("accept", "image/*");
      await userEvent.upload(camera, new File(["jpg"], "boleta.jpg", { type: "image/jpeg" }));
      expect(ingest.mutate).toHaveBeenCalledOnce();
      expect(screen.getByRole("img", { name: "Preview of boleta.jpg" })).toHaveAttribute("src", "blob:receipt");
    });

    it("is only the chat and the box to write in: no placeholder panel, the title is for screen readers", () => {
      phone();
      expect(screen.queryByText("Savings rule")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1, name: "Copilot" })).toHaveClass("sr-only");
      expect(screen.getByLabelText("Ask about your money")).toBeInTheDocument();
    });

    it("grows the box upward as the message gets longer, up to a limit, then scrolls inside", async () => {
      const scrollHeight = vi.spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get");
      scrollHeight.mockReturnValue(44);
      phone();
      const box = screen.getByLabelText("Ask about your money") as HTMLTextAreaElement;
      expect(box.style.height).toBe("44px");

      scrollHeight.mockReturnValue(96);
      await userEvent.type(box, "a longer question{Shift>}{Enter}{/Shift}over several lines");
      expect(box.style.height).toBe("96px");
      expect(box.style.overflowY).toBe("hidden");

      scrollHeight.mockReturnValue(600);
      await userEvent.type(box, " and more");
      expect(box.style.height).toBe("144px");
      expect(box.style.overflowY).toBe("auto");
      scrollHeight.mockRestore();
    });

    it("uses Enter for a new line, since a phone keyboard has no Shift; the arrow button sends", async () => {
      const mutate = vi.fn();
      chat = { ...idle(), mutate };
      phone();
      const box = screen.getByLabelText("Ask about your money");
      await userEvent.type(box, "first line{Enter}second line");
      expect(mutate).not.toHaveBeenCalled();
      expect(box).toHaveValue("first line\nsecond line");

      await userEvent.click(screen.getByRole("button", { name: "Send" }));
      expect(mutate).toHaveBeenCalledWith("first line\nsecond line", expect.anything());
    });

    it("keeps a new conversation one tap away", async () => {
      phone();
      await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
      expect(newSession).toHaveBeenCalled();
    });

    it("offers the suggestions only until the conversation starts", async () => {
      phone();
      const group = () => screen.queryByRole("group", { name: "Suggested questions" });
      expect(group()).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Will I be OK in December?" }));
      expect(group()).not.toBeInTheDocument();
    });
  });

  describe("long messages", () => {
    const send = async (text: string) => {
      render(<MemoryRouter><CopilotPage /></MemoryRouter>);
      fireEvent.change(screen.getByLabelText("Ask about your money"), { target: { value: text } });
      await userEvent.click(screen.getByRole("button", { name: "Send" }));
    };
    const reply = (text: string) => ({ text, actions: [], tools_called: [], facts: [], warnings: [], blocked_reason: null, fallback_used: false, verification: { ok: true } });

    it("wraps a message with no spaces inside the bubble instead of running past the screen", async () => {
      await send("x".repeat(300));
      const bubble = screen.getByText("x".repeat(300)).closest("div")!;
      expect(bubble.className).toContain("[overflow-wrap:anywhere]");
      expect(bubble.className).toContain("min-w-0");
    });

    it("folds a long message behind Show more, like a messaging app, and opens it on demand", async () => {
      const long = "word ".repeat(120).trim();
      await send(long);
      const more = screen.getByRole("button", { name: "Show more" });
      expect(more).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByText(long)).toHaveClass("line-clamp-6");

      await userEvent.click(more);
      expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText(long)).not.toHaveClass("line-clamp-6");
    });

    it("also folds many short lines, and leaves a short message alone", async () => {
      await send(Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n"));
      expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
    });

    it("does not fold a short message", async () => {
      await send("Will I be OK in December?");
      expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    });

    it("folds a very long reply from the Copilot too", async () => {
      const long = "A long answer. ".repeat(110).trim();
      chat = { ...idle(), mutate: vi.fn((_m: string, options?: { onSuccess?: (r: unknown) => void }) => options?.onSuccess?.(reply(long))) };
      await send("hello");
      expect(screen.getAllByRole("button", { name: "Show more" })).toHaveLength(1);
      expect(screen.getByText(long)).toHaveClass("line-clamp-6");
    });
  });

  it("runs a dropped receipt through the workflow, shows each step, then asks the copilot what changed", async () => {
    const steps = [
      { key: "read", status: "done", value: "pdf", by: null, confidence: null },
      { key: "route", status: "done", value: "receipt", by: "jev:jev-1.14", confidence: 0.97 },
      { key: "verify", status: "done", value: "stamp", by: null, confidence: null },
      { key: "categorize", status: "done", value: "groceries", by: "naive_bayes@abc", confidence: 0.54 },
      { key: "match", status: "done", value: "pending", by: null, confidence: null },
      { key: "spending", status: "done", value: "27719", by: null, confidence: null },
    ];
    ingest = { ...idle(), mutate: vi.fn((_input: unknown, options?: { onSuccess?: (e: unknown) => void }) => options?.onSuccess?.({ data: { kind: "receipt", steps, receipt: null } })) };
    chat = { ...idle(), mutate: vi.fn() };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);

    const file = new File(["%PDF"], "boleta.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Add a receipt or a statement", { selector: "input" }), file);

    expect(ingest.mutate).toHaveBeenCalledWith({ file, kind: undefined }, expect.anything());
    const log = screen.getByRole("log");
    expect(log).toHaveTextContent("Added boleta.pdf");
    expect(log).toHaveTextContent("Recognized it: a receipt (boleta)");
    expect(log).toHaveTextContent("by jev:jev-1.14");
    expect(log).toHaveTextContent("Checked the amounts: the SII stamp confirms the total");
    expect(log).toHaveTextContent("Chose a category: Groceries");
    expect(log).toHaveTextContent(/27.719 a day until payday/);
    expect(chat.mutate).toHaveBeenCalledWith("I just added a document. How much can I spend now?", expect.anything());
  });

  it("asks about investments, not spending, after a Fintual document (ADR-044)", async () => {
    const steps = [
      { key: "read", status: "done", value: "pdf", by: null, confidence: null },
      { key: "route", status: "done", value: "investment", by: "rules", confidence: 1 },
      { key: "verify", status: "done", value: "verified", by: null, confidence: null },
      { key: "duplicate", status: "done", value: "new", by: null, confidence: null },
      { key: "investments", status: "done", value: "holdings", by: null, confidence: null },
    ];
    ingest = { ...idle(), mutate: vi.fn((_input: unknown, options?: { onSuccess?: (e: unknown) => void }) => options?.onSuccess?.({ data: { kind: "investment", steps, receipt: null } })) };
    chat = { ...idle(), mutate: vi.fn() };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);

    await userEvent.upload(screen.getByLabelText("Add a receipt or a statement", { selector: "input" }), new File(["%PDF"], "cartola-fintual.pdf", { type: "application/pdf" }));

    const log = screen.getByRole("log");
    expect(log).toHaveTextContent("Recognized it: an investment document");
    expect(log).toHaveTextContent("Updated what it knows of your investments: your investment statement");
    expect(chat.mutate).toHaveBeenCalledWith("I just added my investment documents. How are my investments doing?", expect.anything());
  });

  it("refuses a file over 15 MB before sending it", async () => {
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const big = new File(["x"], "scan.jpg", { type: "image/jpeg" });
    Object.defineProperty(big, "size", { value: 15 * 1024 * 1024 + 1 });
    await userEvent.upload(screen.getByLabelText("Add a receipt or a statement", { selector: "input" }), big);
    expect(ingest.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole("log")).toHaveTextContent("larger than 15 MB");
  });

  it("takes a file dropped anywhere on the chat and shows what was sent", () => {
    ingest = { ...idle(), mutate: vi.fn() };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const chatArea = screen.getByRole("region", { name: "Copilot" });
    const file = new File(["%PDF"], "boleta.pdf", { type: "application/pdf" });
    const dataTransfer = { files: [file], types: ["Files"], dropEffect: "none" };

    fireEvent.dragEnter(chatArea, { dataTransfer });
    expect(chatArea).toHaveTextContent("Drop it here to add it to the chat");
    fireEvent.drop(chatArea, { dataTransfer });

    expect(ingest.mutate).toHaveBeenCalledWith({ file, kind: undefined }, expect.anything());
    expect(chatArea).not.toHaveTextContent("Drop it here");
    expect(screen.getByRole("log").querySelector("figure")).toHaveTextContent("boleta.pdf");
  });

  it("ignores text dragged over the chat", () => {
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const chatArea = screen.getByRole("region", { name: "Copilot" });
    fireEvent.dragEnter(chatArea, { dataTransfer: { files: [], types: ["text/plain"] } });
    expect(chatArea).not.toHaveTextContent("Drop it here");
    expect(ingest.mutate).not.toHaveBeenCalled();
  });

  const unreadableDate = {
    receipt_id: "rcpt_1", issuer: { untrusted_text: "SUPERMERCADO" }, issued_on: null, total: 30000, currency: "CLP", folio: null,
    stamped: false, source: "ocr", category: "groceries", classifier: "nb", verified: false,
    issues: [{ code: "DATE_MISSING", message: "the date could not be read" }], matched_transaction: null, duplicate: false, counted: false, corrected: false,
  };

  it("asks for what the reader could not read and sends the user's correction, then asks the copilot again", async () => {
    const steps = [{ key: "verify", status: "warning", value: "DATE_MISSING", by: null, confidence: null }];
    ingest = { ...idle(), mutate: vi.fn((_input: unknown, options?: { onSuccess?: (e: unknown) => void }) => options?.onSuccess?.({ data: { kind: "receipt", steps, receipt: unreadableDate } })) };
    correction = { ...idle(), mutate: vi.fn((_fix: unknown, options?: { onSuccess?: (e: unknown) => void }) => options?.onSuccess?.({ data: { ...unreadableDate, issued_on: "2026-10-16", verified: true, issues: [], counted: true, corrected: true } })) };
    chat = { ...idle(), mutate: vi.fn() };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    await userEvent.upload(screen.getByLabelText("Add a receipt or a statement", { selector: "input" }), new File(["jpg"], "boleta.jpg", { type: "image/jpeg" }));

    const form = screen.getByRole("form", { name: "Correct the receipt" });
    expect(form).toHaveTextContent("I could not read everything. What does the receipt say?");
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-10-16" } });
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));

    expect(correction.mutate).toHaveBeenCalledWith({ receiptId: "rcpt_1", issued_on: "2026-10-16" }, expect.anything());
    expect(chat.mutate).toHaveBeenLastCalledWith("I corrected the receipt. How much can I spend now?", expect.anything());
    expect(screen.getByRole("log")).toHaveTextContent("Corrected by you.");
  });

  it("lets the user say what a file is when it was not recognized", async () => {
    const { ApiError } = await import("@/api/client");
    const unknown = new ApiError(422, { status: "INVALID_INPUT", field: "file", allowed: ["statement", "receipt"], message: "this does not look like a bank statement or a receipt" });
    ingest = { ...idle(), mutate: vi.fn((_input: unknown, options?: { onError?: (e: unknown) => void }) => options?.onError?.(unknown)) };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    const file = new File(["jpg"], "cuenta.jpg", { type: "image/jpeg" });
    await userEvent.upload(screen.getByLabelText("Add a receipt or a statement", { selector: "input" }), file);

    expect(screen.getByRole("group", { name: "I could not tell what this is. What did you add?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "It is a receipt" }));
    expect(ingest.mutate).toHaveBeenLastCalledWith({ file, kind: "receipt" }, expect.anything());
  });

  it("shows an expense said in chat for the user to complete and confirm, without an amount to edit", async () => {
    const expense = {
      proposal_id: "exp_1", amount: 15000, currency: "CLP", description: { untrusted_text: "Hoy gasté 15 lucas en el almuerzo" },
      spent_on: "2026-10-19", category: "uncategorized", payment: "unknown", missing: ["payment", "category"],
    };
    const reply = { text: "Was it paid in cash or by card?", actions: [], tools_called: ["propose_expense"], facts: [], warnings: [], blocked_reason: null, fallback_used: false, verification: { ok: true }, pending_expense: expense };
    chat = { ...idle(), mutate: vi.fn((_m: string, options?: { onSuccess?: (r: unknown) => void }) => options?.onSuccess?.(reply)) };
    expenseConfirm = { ...idle(), mutate: vi.fn((_c: unknown, options?: { onSuccess?: () => void }) => options?.onSuccess?.()) };
    render(<MemoryRouter><CopilotPage /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Ask about your money"), "Hoy gasté 15 lucas en el almuerzo{enter}");

    const card = screen.getByRole("form", { name: "Expense to confirm" });
    expect(card).toHaveTextContent(/15.000/);
    expect(within(card).queryAllByRole("textbox")).toHaveLength(0); // the amount is not editable
    const confirmButton = within(card).getByRole("button", { name: "Confirm expense" });
    expect(confirmButton).toBeDisabled(); // cash or card first
    await userEvent.click(within(card).getByText("Card"));
    await userEvent.selectOptions(within(card).getByLabelText("Category"), "dining");
    await userEvent.click(confirmButton);

    expect(expenseConfirm.mutate).toHaveBeenCalledWith({ proposalId: "exp_1", payment: "card", category: "dining" }, expect.anything());
    expect(chat.mutate).toHaveBeenLastCalledWith("I saved the expense. How much can I spend now?", expect.anything());
  });

  describe("a reply built on memory (ADR-048 §6)", () => {
    const at = (consent_generation: number, memory_revision: number) => ({ consent_generation, memory_revision });
    const base = { actions: [], warnings: [], blocked_reason: null, fallback_used: false, verification: { ok: true } };
    const salaryReply = (dependency: ReturnType<typeof at> | null, extra: object = {}) => ({
      ...base, text: "You declared a net salary of 1,234,567 CLP.", tools_called: ["get_user_memory"],
      facts: [{ key: "memory.salary_net_1.amount", value: 1234567, unit: "CLP" }], memory_dependency: dependency, ...extra,
    });
    const answering = (...replies: unknown[]) => {
      const queue = [...replies];
      chat = { ...idle(), mutate: vi.fn((_m: string, options?: { onSuccess?: (r: unknown) => void }) => options?.onSuccess?.(queue.shift())) };
    };
    const ask = (name = "Will I be OK in December?") => userEvent.click(screen.getByRole("button", { name }));
    const log = () => screen.getByRole("log");

    it("hides the whole reply, even one with no card, when the tab already knows memory moved (a late response)", async () => {
      counters = at(2, 1); // revoked in the profile while the request was in flight
      answering(salaryReply(at(1, 1)));
      render(<MemoryRouter><CopilotPage /></MemoryRouter>);
      await ask();
      expect(log()).not.toHaveTextContent("1,234,567");
      expect(log()).not.toHaveTextContent("get_user_memory");
      expect(log()).toHaveTextContent("Your memory settings changed after this reply was written");
    });

    it("never shows an older reply again when responses arrive out of order", async () => {
      counters = at(1, 2);
      answering(salaryReply(at(1, 2), { text: "Newer: 1,300,000 CLP." }), salaryReply(at(1, 1)));
      render(<MemoryRouter><CopilotPage /></MemoryRouter>);
      await ask();
      await ask("Just make it work.");
      expect(log()).toHaveTextContent("Newer: 1,300,000 CLP.");
      expect(log()).not.toHaveTextContent("1,234,567");
    });

    it("hides a reply that was shown once memory moves, and its proposal with it", async () => {
      counters = at(1, 1);
      const proposal = {
        proposal_id: "prop_dep", session_id: "s1", user_id: "camila", source_snapshot_id: "plan_1", status: "pending",
        created_at: "2026-10-29T12:00:00-03:00", expires_at: "2099-10-29T12:30:00-03:00",
        terms: { action: "create_savings_rule", amount: 777000, currency: "CLP", frequency: "monthly", source_account: "checking", destination: "sandbox_savings", effective_date: "2027-01-01" },
      };
      answering(salaryReply(at(1, 1), { pending_proposal: proposal }));
      const view = render(<MemoryRouter><CopilotPage /></MemoryRouter>);
      await ask();
      expect(log()).toHaveTextContent("1,234,567");
      expect(document.body).toHaveTextContent("777,000");

      counters = at(2, 1);
      view.rerender(<MemoryRouter><CopilotPage /></MemoryRouter>);
      expect(log()).not.toHaveTextContent("1,234,567");
      expect(document.body).not.toHaveTextContent("777,000");
    });

    it("keeps showing a reply that did not rely on memory", async () => {
      counters = at(5, 5);
      answering({ ...base, text: "Not comfortably.", tools_called: [], facts: [], memory_dependency: null });
      render(<MemoryRouter><CopilotPage /></MemoryRouter>);
      await ask();
      expect(log()).toHaveTextContent("Not comfortably.");
    });
  });
});
