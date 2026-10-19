import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CopilotPage } from "./CopilotPage";

let sessionId = "ui-camila-first";
const newSession = vi.fn(() => {
  sessionId = "ui-camila-second";
});
const idle = () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, error: null });
let chat: ReturnType<typeof idle> = idle();
afterEach(() => { chat = idle(); vi.useRealTimers(); });

vi.mock("@/api/hooks", () => ({
  usePersona: () => ({ persona: "camila", sessionId, newSession }),
  useFinancialState: () => ({ data: undefined }),
  usePending: () => ({ data: undefined }),
  useHealth: () => ({ data: undefined }),
  useChat: () => chat,
  useConfirmProposal: () => idle(),
  useExecute: () => idle(),
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

    it("is only the chat and the box to write in: no placeholder panel, the title is for screen readers", () => {
      phone();
      expect(screen.queryByText("Savings rule")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1, name: "Copilot" })).toHaveClass("sr-only");
      expect(screen.getByLabelText("Ask about your money")).toBeInTheDocument();
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
});
