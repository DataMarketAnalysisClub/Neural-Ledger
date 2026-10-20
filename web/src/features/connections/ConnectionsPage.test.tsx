import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ConnectionsPage } from "./ConnectionsPage";

const ok = (data: unknown) => ({ status: "OK", params_version: "cn-0.1", facts: [], warnings: [], data });
const idle = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined });

const app = {
  connection_id: "conn_1",
  kind: "mcp",
  name: "Racional",
  host: "mcp.example.com",
  created_at: "2026-10-29T12:00:00-03:00",
  last_synced_at: null,
  tools: [
    { name: "get_portfolio", description: { untrusted_text: "<img src=x onerror=alert(1)> Saldo" }, read_only_hint: true, destructive_hint: null, blocked: null, enabled: false },
    { name: "invest", description: { untrusted_text: "Invierte" }, read_only_hint: false, destructive_hint: null, blocked: "WRITE_VERB", enabled: false },
  ],
};

let mode: string;
let add: ReturnType<typeof idle>;
let setTools: ReturnType<typeof idle>;

vi.mock("@/api/hooks", () => ({
  usePersona: () => ({ persona: "camila", sessionId: "s", identity: { kind: "demo", user_id: "camila" } }),
  useConnections: () => ({ isPending: false, isError: false, refetch: vi.fn(), data: ok({ connections: [app], mode, bank: { aggregator: "fintoc", public_key: null } }) }),
  useConnectedData: () => ({ data: undefined }),
  useAddConnection: () => add,
  useSetConnectionTools: () => setTools,
  useSyncConnection: () => idle(),
  useRemoveConnection: () => idle(),
  useBankStart: () => idle(),
  useConnectBank: () => idle(),
}));

function renderPage() {
  return render(<MemoryRouter><ConnectionsPage /></MemoryRouter>);
}

describe("ConnectionsPage", () => {
  beforeEach(() => {
    mode = "fixture";
    add = idle();
    setTools = idle();
  });

  it("blocks a writing tool and shows server text as text", async () => {
    renderPage();
    expect(screen.getByRole("checkbox", { name: "invest" })).toBeDisabled();
    expect(screen.getByText("Blocked: its name says it changes something")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull(); // the description is text, never markup
    await userEvent.click(screen.getByRole("checkbox", { name: "get_portfolio" }));
    await userEvent.click(screen.getByRole("button", { name: "Save choice" }));
    expect(setTools.mutate).toHaveBeenCalledWith({ id: "conn_1", enabled: ["get_portfolio"] });
  });

  it("connects an app only after consent", async () => {
    renderPage();
    const submit = screen.getByRole("button", { name: "Connect" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Name"), "Fintual");
    await userEvent.type(screen.getByLabelText("MCP server address"), "https://mcp.example.com/mcp");
    await userEvent.click(screen.getAllByRole("checkbox", { name: /I agree/ })[1]!);
    await userEvent.click(submit);
    expect(add.mutate).toHaveBeenCalledWith({ name: "Fintual", url: "https://mcp.example.com/mcp", token: null }, expect.anything());
  });

  it("says when the server has connections turned off", () => {
    mode = "off";
    renderPage();
    expect(screen.getByText("Connections are turned off on this server")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });
});
