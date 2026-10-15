import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { accountsApi } from "@/api/accounts";
import { PersonaProvider } from "@/api/hooks";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { AuthProvider, useAuth } from "./AuthProvider";
import { SignUpPage } from "./AuthPages";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

function AuthProbe() {
  const auth = useAuth();
  return <div>
    <span data-testid="identity">{auth.me?.user_id ?? "anonymous"}</span>
    <button type="button" onClick={() => void auth.signup({ email: "probe@example.invalid", password: "synthetic-password", display_name: "Probe" })}>Create</button>
    <button type="button" onClick={() => void auth.signin({ email: "probe@example.invalid", password: "synthetic-password" })}>Sign in</button>
    <button type="button" onClick={() => void auth.explore("camila")}>Explore</button>
    <button type="button" onClick={() => void auth.signout()}>Sign out</button>
  </div>;
}

function deferredResponse() {
  let deliver: ((response: Response) => void) | undefined;
  const promise = new Promise<Response>((resolve) => { deliver = resolve; });
  return { promise, resolve(response: Response) { deliver?.(response); } };
}

function PersonaProfile() {
  const auth = useAuth();
  if (auth.pending) return <div role="status">Loading</div>;
  return <PersonaProvider><ProfilePage /></PersonaProvider>;
}

const expiry = "2026-10-15T12:00:00Z";

describe("accounts session", () => {
  it("clears prior user queries when signup establishes a new identity", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    let signedIn = false;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
      if (path.endsWith("/v1/auth/signup")) { signedIn = true; return new Response(JSON.stringify({ user_id: "usr_probe", expires_at: expiry }), { status: 201 }); }
      if (path.endsWith("/v1/me")) return new Response(JSON.stringify(signedIn ? { user_id: "usr_probe", data_source: "empty", expires_at: expiry } : { status: "UNAUTHENTICATED", message: "authentication required" }), { status: signedIn ? 200 : 401 });
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

  it("ignores an older successful me response after signout clears the user cache", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const older = deferredResponse();
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
      if (path.endsWith("/v1/me")) return older.promise;
      if (path.endsWith("/v1/auth/signout")) return new Response(null, { status: 204 });
      return new Response("{}", { status: 404 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["usr_old", "profile"], { private: "old user" });
    render(<QueryClientProvider client={client}><AuthProvider><AuthProbe /></AuthProvider></QueryClientProvider>);
    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/me"))).toHaveLength(1));

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(client.getQueryData(["usr_old", "profile"])).toBeUndefined());
    await act(async () => {
      older.resolve(new Response(JSON.stringify({ user_id: "usr_old", data_source: "persona", expires_at: expiry }), { status: 200 }));
      await older.promise;
    });

    expect(screen.getByTestId("identity")).toHaveTextContent("anonymous");
    expect(client.getQueryData(["usr_old", "profile"])).toBeUndefined();
  });

  it.each([
    { label: "Create", endpoint: "/v1/auth/signup", user: "usr_probe", source: "empty", status: 201 },
    { label: "Sign in", endpoint: "/v1/auth/signin", user: "usr_probe", source: "empty", status: 200 },
    { label: "Explore", endpoint: "/v1/auth/demo-session", user: "camila", source: "persona", status: 200 },
  ])("keeps the new $label identity when an older me response arrives late", async ({ label, endpoint, user, source, status }) => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const older = deferredResponse();
    let meRequests = 0;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
      if (path.endsWith(endpoint)) return new Response(JSON.stringify({ user_id: user, expires_at: expiry }), { status });
      if (path.endsWith("/v1/me")) {
        meRequests += 1;
        return meRequests === 1 ? older.promise : new Response(JSON.stringify({ user_id: user, data_source: source, expires_at: expiry }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["usr_old", "profile"], { private: "old user" });
    render(<QueryClientProvider client={client}><AuthProvider><AuthProbe /></AuthProvider></QueryClientProvider>);
    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/me"))).toHaveLength(1));

    await userEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(screen.getByTestId("identity")).toHaveTextContent(user));
    expect(client.getQueryData(["usr_old", "profile"])).toBeUndefined();
    client.setQueryData([user, "profile"], { private: "new user" });
    await act(async () => {
      older.resolve(new Response(JSON.stringify({ user_id: "usr_old", data_source: "sample", expires_at: expiry }), { status: 200 }));
      await older.promise;
    });

    expect(screen.getByTestId("identity")).toHaveTextContent(user);
    expect(client.getQueryData([user, "profile"])).toEqual({ private: "new user" });
  });

  it("keeps a new signin when an older me request answers 401", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const older = deferredResponse();
    let meRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/health")) return new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 });
      if (path.endsWith("/v1/auth/signin")) return new Response(JSON.stringify({ user_id: "usr_probe", expires_at: expiry }), { status: 200 });
      if (path.endsWith("/v1/me")) {
        meRequests += 1;
        return meRequests === 1 ? older.promise : new Response(JSON.stringify({ user_id: "usr_probe", data_source: "empty", expires_at: expiry }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AuthProvider><AuthProbe /></AuthProvider></QueryClientProvider>);
    await waitFor(() => expect(meRequests).toBe(1));

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByTestId("identity")).toHaveTextContent("usr_probe"));
    client.setQueryData(["usr_probe", "profile"], { private: "new user" });
    await act(async () => {
      older.resolve(new Response(JSON.stringify({ status: "UNAUTHENTICATED", message: "authentication required" }), { status: 401 }));
      await older.promise;
    });

    expect(screen.getByTestId("identity")).toHaveTextContent("usr_probe");
    expect(client.getQueryData(["usr_probe", "profile"])).toEqual({ private: "new user" });
  });

  it("shows a demo persona's permitted capacity without sample-data controls", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "true");
    await accountsApi.demoSession("camila");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter><AuthProvider><PersonaProfile /></AuthProvider></MemoryRouter></QueryClientProvider>);

    await waitFor(() => expect(screen.getByText("Limited by capacity")).toBeInTheDocument());

    expect(screen.getByText("This synthetic demo profile is read only.")).toBeInTheDocument();
    expect(screen.getByText("Aggressive", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Conservative", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Financial capacity: Conservative")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data is on. This version has no remove-sample action.")).not.toBeInTheDocument();
  });

  it("offers a labelled signup form without axe violations", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).endsWith("/health")
      ? new Response(JSON.stringify({ auth: "accounts", mode: "offline" }), { status: 200 })
      : new Response(JSON.stringify({ status: "UNAUTHENTICATED", message: "authentication required" }), { status: 401 }));
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
