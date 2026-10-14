import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { AuthProvider, useAuth } from "./AuthProvider";
import { SignUpPage } from "./AuthPages";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

function AuthProbe() {
  const auth = useAuth();
  return <div>
    <span>{auth.me?.user_id ?? "anonymous"}</span>
    <button type="button" onClick={() => void auth.signup({ email: "probe@example.invalid", password: "synthetic-password", display_name: "Probe" })}>Create</button>
  </div>;
}

describe("accounts session", () => {
  it("clears prior user queries when signup establishes a new identity", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    let signedIn = false;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
      if (path.endsWith("/v1/auth/signup")) { signedIn = true; return new Response("{}", { status: 201 }); }
      if (path.endsWith("/v1/me")) return new Response(JSON.stringify(signedIn ? { user_id: "usr_probe", data_source: "empty" } : { status: "UNAUTHENTICATED" }), { status: signedIn ? 200 : 401 });
      return new Response("{}", { status: 404 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["usr_previous", "state"], { private: true });
    render(<QueryClientProvider client={client}><AuthProvider><AuthProbe /></AuthProvider></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText("anonymous")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(screen.getByText("usr_probe")).toBeInTheDocument());
    expect(client.getQueryData(["usr_previous", "state"])).toBeUndefined();
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/me")).every(([, init]) => !Object.hasOwn(init?.headers ?? {}, "X-User-Id"))).toBe(true);
  });

  it("offers a labelled signup form without axe violations", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).endsWith("/health")
      ? new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 })
      : new Response(JSON.stringify({ status: "UNAUTHENTICATED" }), { status: 401 }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/signup"]}>
      <AuthProvider><Routes><Route path="/signup" element={<SignUpPage />} /></Routes></AuthProvider>
    </MemoryRouter></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument());

    const results = await axe(container);

    expect(results.violations).toEqual([]);
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "new-password");
  });
});
