import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CopilotPage } from "./CopilotPage";

let sessionId = "ui-camila-first";
const newSession = vi.fn(() => {
  sessionId = "ui-camila-second";
});
const idle = () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, error: null });

vi.mock("@/api/hooks", () => ({
  usePersona: () => ({ persona: "camila", sessionId, newSession }),
  useFinancialState: () => ({ data: undefined }),
  usePending: () => ({ data: undefined }),
  useHealth: () => ({ data: undefined }),
  useChat: () => idle(),
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
});
