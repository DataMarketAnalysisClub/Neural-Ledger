import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { PersonaProvider } from "@/api/hooks";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { ProfilePage } from "./ProfilePage";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

const expiry = "2026-10-15T12:00:00Z";
const profile = (user_id: string, name: string) => ({
  status: "OK", params_version: "fc-0.3", facts: [], warnings: [],
  data: { user_id, display_name: { untrusted_text: name }, language: "en", declared_tolerance: null, questionnaire_version: null, questionnaire: [] },
});

function Page() {
  const auth = useAuth();
  if (auth.pending) return <div role="status">Loading</div>;
  return <PersonaProvider><ProfilePage /></PersonaProvider>;
}

function serve(user_id: string, data_source: string, deletion: () => Response) {
  let signedIn = true;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
    if (path.endsWith("/v1/me")) return signedIn
      ? new Response(JSON.stringify({ user_id, data_source, expires_at: expiry }), { status: 200 })
      : new Response(JSON.stringify({ status: "UNAUTHENTICATED", message: "sign in required" }), { status: 401 });
    if (path.endsWith("/v1/account") && init?.method === "DELETE") {
      const response = deletion();
      if (response.status === 200 && data_source !== "persona") signedIn = false;
      return response;
    }
    if (path.endsWith("/v1/profile")) return new Response(JSON.stringify(profile(user_id, user_id === "camila" ? "Camila" : "Ana")), { status: 200 });
    return new Response(JSON.stringify({ status: "INSUFFICIENT_DATA", params_version: "fc-0.3", missing: ["financial data"], facts: [], warnings: [] }), { status: 409 });
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/profile"]}>
    <AuthProvider><Routes><Route path="/profile" element={<Page />} /><Route path="/signin" element={<p>sign in page</p>} /></Routes></AuthProvider>
  </MemoryRouter></QueryClientProvider>);
}

describe("account deletion", () => {
  it("asks for the confirmation word and the password, sends both, and signs the user out", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const fetch = serve("usr_ana", "empty", () => new Response(JSON.stringify({ status: "DELETED", erased: { user_accounts: 1 }, audit_events_erased: 3 }), { status: 200 }));
    const { container } = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete account" }));

    expect((await axe(container)).violations).toEqual([]);
    const submit = screen.getByRole("button", { name: "Delete my account permanently" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type DELETE or your email to confirm"), "DELETE");
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your password"), "synthetic-password");
    await userEvent.click(submit);

    await waitFor(() => expect(screen.getByText("sign in page")).toBeInTheDocument());
    const call = fetch.mock.calls.find(([url, init]) => String(url).endsWith("/v1/account") && init?.method === "DELETE");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirm: "DELETE", password: "synthetic-password" });
  });

  it("shows the server's refusal and keeps the user signed in", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    serve("usr_ana", "empty", () => new Response(JSON.stringify({ status: "INVALID_CREDENTIALS", message: "invalid credentials" }), { status: 401 }));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete account" }));
    await userEvent.type(screen.getByLabelText("Type DELETE or your email to confirm"), "DELETE");
    await userEvent.type(screen.getByLabelText("Your password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account permanently" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("sign in page")).not.toBeInTheDocument();
  });

  it("offers a demo persona a reset, never a deletion, with RESET and no password", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const fetch = serve("camila", "persona", () => new Response(JSON.stringify({ status: "RESET", erased: { statements: 1 }, audit_events_erased: 4 }), { status: 200 }));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reset demo data" }));
    expect(screen.queryByLabelText("Your password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete account" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Type RESET to confirm"), "RESET");
    await userEvent.click(screen.getByRole("button", { name: "Reset this persona's data" }));

    expect(await screen.findByText("Demo data reset. 4 audit events erased.")).toBeInTheDocument();
    const call = fetch.mock.calls.find(([url, init]) => String(url).endsWith("/v1/account") && init?.method === "DELETE");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirm: "RESET" });
  });
});
