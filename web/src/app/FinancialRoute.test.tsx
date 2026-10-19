import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FinancialRoute } from "./FinancialRoute";

/** ADR-029: an account's financial screens open once its model can come from its own statements. */
let auth: { mode: "demo" | "accounts"; me: { data_source: string } | null };
vi.mock("@/features/auth/AuthProvider", () => ({ useAuth: () => auth }));

function mount() {
  render(<MemoryRouter><FinancialRoute><p>forecast screen</p></FinancialRoute></MemoryRouter>);
}

afterEach(() => vi.unstubAllEnvs());

describe("FinancialRoute", () => {
  it.each(["persona", "statements"])("opens the screen to an account whose data source is %s", (source) => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    auth = { mode: "accounts", me: { data_source: source } };
    mount();
    expect(screen.getByText("forecast screen")).toBeInTheDocument();
  });

  it("opens every screen in demo mode", () => {
    auth = { mode: "demo", me: null };
    mount();
    expect(screen.getByText("forecast screen")).toBeInTheDocument();
  });

  it("asks an empty account to import its statements, linking to the Statements page", () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    auth = { mode: "accounts", me: { data_source: "empty" } };
    mount();
    expect(screen.queryByText("forecast screen")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("No financial data yet");
    expect(screen.getByText(/at least 7 months/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import statements" })).toHaveAttribute("href", "/statements");
  });
});
