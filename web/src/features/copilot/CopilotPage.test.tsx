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
});
