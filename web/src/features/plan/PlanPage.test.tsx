import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { PersonaProvider, usePersona } from "@/api/hooks";
import type { PersonaId } from "@/api/client";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { PlanPage } from "./PlanPage";

type Tolerance = "conservative" | "moderate" | "aggressive";
type Call = { readonly path: string; readonly user: string; readonly body: string | undefined };

function reply(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function envelope(data: unknown) {
  return { status: "OK", params_version: "fc-0.1", snapshot_id: "snapshot", facts: [], warnings: [], data };
}

function profile(tolerance: Tolerance | null, user: PersonaId = "camila"): Response {
  return reply(envelope({ user_id: user, display_name: { untrusted_text: user === "camila" ? "Camila" : "Diego" }, language: "en", declared_tolerance: tolerance, questionnaire_version: null, questionnaire: [] }));
}

function delayedResponse() {
  let complete: (response: Response) => void;
  const promise = new Promise<Response>((resolve) => { complete = resolve; });
  return { promise, complete: (response: Response) => complete(response) };
}

function mockApi(profileAnswer: (user: string) => Response | Promise<Response>): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, options) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const user = new Headers(options?.headers).get("X-User-Id") ?? "";
    const body = options?.body?.toString();
    calls.push({ path, user, body });
    if (path === "/api/v1/profile") return Promise.resolve(profileAnswer(user));
    if (path === "/api/v1/state") return Promise.resolve(reply(envelope({ user_id: user, currency: "CLP" })));
    if (path === "/api/v1/capacity") return Promise.resolve(reply(envelope({ level: "conservative", binding_factors: [], factors: [] })));
    if (path === "/api/v1/permitted-profile") {
      const payload: unknown = JSON.parse(body ?? "null");
      const tolerance = payload && typeof payload === "object" && "tolerance" in payload ? payload.tolerance : null;
      return Promise.resolve(reply(envelope({ tolerance, capacity: "conservative", permitted: "conservative", hard_rules_triggered: [] })));
    }
    if (path === "/api/v1/savings-plan") {
      return Promise.resolve(reply(envelope({ amount: user === "camila" ? 100000 : 0, start_month: user === "camila" ? "2027-01" : null, hard_rules_triggered: [], requirements: [], goal_status: [] })));
    }
    return Promise.resolve(reply({ message: `Unexpected request: ${path}` }, 404));
  });
  return calls;
}

function SwitchPersona() {
  const { setPersona } = usePersona();
  return <button onClick={() => setPersona("diego")}>View Diego</button>;
}

function AccountPlan() {
  const auth = useAuth();
  return <>
    <button type="button" onClick={() => void auth.signin({ email: "second@example.invalid", password: "synthetic-password" })}>Sign in as second account</button>
    {!auth.pending && auth.me && <PersonaProvider><PlanPage /></PersonaProvider>}
  </>;
}

function showPlan(initial: PersonaId = "camila") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PersonaProvider initial={initial}>
          <SwitchPersona />
          <PlanPage />
        </PersonaProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function toleranceSection() {
  return within(screen.getByRole("region", { name: "How much risk the plan may take" }));
}

function displayedTolerance() {
  return toleranceSection().getByText("Your tolerance").nextElementSibling;
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("PlanPage stored tolerance", () => {
  it.each([
    ["camila", "aggressive", "Aggressive"],
    ["diego", "moderate", "Moderate"],
  ] as const)("shows %s's declared %s tolerance without a client-side override", async (persona, declared, label) => {
    const calls = mockApi(() => profile(declared, persona));

    showPlan(persona);

    await waitFor(() => expect(displayedTolerance()).toHaveTextContent(label));
    expect(toleranceSection().queryByRole("radio")).toBeNull();
    expect(calls).toContainEqual({ path: "/api/v1/profile", user: persona, body: undefined });
    expect(calls).toContainEqual({ path: "/api/v1/permitted-profile", user: persona, body: JSON.stringify({ tolerance: declared }) });
    await waitFor(() => expect(calls).toContainEqual({ path: "/api/v1/savings-plan", user: persona, body: JSON.stringify({ permitted_profile: "conservative" }) }));
  });

  it.each([
    ["no declaration", () => profile(null)],
    ["endpoint unavailable", () => reply({ detail: "Not Found" }, 404)],
  ] as const)("uses conservative for %s", async (_condition, answer) => {
    const calls = mockApi(answer);

    showPlan();

    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Conservative"));
    expect(calls).toContainEqual({ path: "/api/v1/permitted-profile", user: "camila", body: JSON.stringify({ tolerance: "conservative" }) });
    expect(toleranceSection().queryByRole("radio")).toBeNull();
  });

  it("waits for the profile before requesting a permitted profile or plan", async () => {
    const pending = delayedResponse();
    const calls = mockApi(() => pending.promise);

    showPlan();
    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/profile")).toBe(true));
    expect(screen.queryByRole("region", { name: "How much risk the plan may take" })).toBeNull();
    expect(calls.some((call) => call.path === "/api/v1/permitted-profile" || call.path === "/api/v1/savings-plan")).toBe(false);

    await act(async () => pending.complete(profile("moderate")));
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Moderate"));
    expect(calls).toContainEqual({ path: "/api/v1/permitted-profile", user: "camila", body: JSON.stringify({ tolerance: "moderate" }) });
  });

  it("hides the old persona's tolerance while the new persona profile is pending", async () => {
    const diego = delayedResponse();
    const calls = mockApi((user) => user === "diego" ? diego.promise : profile("aggressive"));
    showPlan();
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Aggressive"));

    await userEvent.click(screen.getByRole("button", { name: "View Diego" }));
    expect(screen.queryByRole("region", { name: "How much risk the plan may take" })).toBeNull();
    expect(calls.some((call) => call.path === "/api/v1/permitted-profile" && call.user === "diego")).toBe(false);
    await act(async () => diego.complete(profile("moderate", "diego")));
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Moderate"));
    expect(calls).toContainEqual({ path: "/api/v1/permitted-profile", user: "diego", body: JSON.stringify({ tolerance: "moderate" }) });
  });

  it("does not apply a late old-persona profile response to the current persona", async () => {
    const camila = delayedResponse();
    const calls = mockApi((user) => user === "camila" ? camila.promise : profile("moderate", "diego"));
    showPlan();
    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/profile" && call.user === "camila")).toBe(true));

    await userEvent.click(screen.getByRole("button", { name: "View Diego" }));
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Moderate"));
    await act(async () => camila.complete(profile("aggressive")));

    expect(displayedTolerance()).toHaveTextContent("Moderate");
    expect(calls.filter((call) => call.path === "/api/v1/permitted-profile" && call.user === "diego")).toEqual([
      { path: "/api/v1/permitted-profile", user: "diego", body: JSON.stringify({ tolerance: "moderate" }) },
    ]);
  });

  it("reads each account's own stored tolerance without a demo identity header or shared profile cache", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    let accountId = "usr_first";
    const secondProfile = delayedResponse();
    const profileFor = (userId: string) => reply(envelope({
      user_id: userId, display_name: { untrusted_text: "Test Account" }, language: "en",
      declared_tolerance: userId === "usr_first" ? "aggressive" : "moderate",
      questionnaire_version: null, questionnaire: [],
    }));
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return reply({ auth: "accounts", mode: "offline" });
      if (path === "/api/v1/auth/signin") {
        accountId = "usr_second";
        return reply({ user_id: accountId, expires_at: "2099-01-01T00:00:00Z" });
      }
      if (path === "/api/v1/me") return reply({ user_id: accountId, data_source: "sample", expires_at: "2099-01-01T00:00:00Z" });
      if (path === "/api/v1/profile") return accountId === "usr_first" ? profileFor(accountId) : secondProfile.promise;
      if (path === "/api/v1/state") return reply(envelope({ user_id: accountId, currency: "CLP" }));
      if (path === "/api/v1/capacity") return reply(envelope({ level: "conservative", binding_factors: [], factors: [] }));
      if (path === "/api/v1/permitted-profile") {
        const body: unknown = JSON.parse(options?.body?.toString() ?? "null");
        const tolerance = body && typeof body === "object" && "tolerance" in body ? body.tolerance : null;
        return reply(envelope({ tolerance, capacity: "conservative", permitted: "conservative", hard_rules_triggered: [] }));
      }
      if (path === "/api/v1/savings-plan") return reply(envelope({ amount: 0, start_month: null, hard_rules_triggered: [], requirements: [], goal_status: [] }));
      return reply({ message: `Unexpected request: ${path}` }, 404);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter><AuthProvider><AccountPlan /></AuthProvider></MemoryRouter></QueryClientProvider>);
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Aggressive"));
    expect(client.getQueryData(["usr_first", "profile"])).toMatchObject({ data: { user_id: "usr_first", declared_tolerance: "aggressive" } });

    await userEvent.click(screen.getByRole("button", { name: "Sign in as second account" }));
    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/v1/profile"))).toHaveLength(2));
    expect(screen.queryByRole("region", { name: "How much risk the plan may take" })).toBeNull();
    await act(async () => secondProfile.complete(profileFor("usr_second")));
    await waitFor(() => expect(displayedTolerance()).toHaveTextContent("Moderate"));

    expect(client.getQueryData(["usr_first", "profile"])).toBeUndefined();
    expect(client.getQueryData(["usr_second", "profile"])).toMatchObject({ data: { user_id: "usr_second", declared_tolerance: "moderate" } });
    expect(client.getQueryData(["camila", "profile"])).toBeUndefined();
    const accountCalls = fetch.mock.calls.filter(([url]) => /\/v1\/(profile|state|capacity|permitted-profile|savings-plan)$/.test(String(url)));
    expect(accountCalls.every(([, options]) => options?.credentials === "same-origin" && !new Headers(options.headers).has("X-User-Id"))).toBe(true);
    expect(accountCalls.filter(([url]) => String(url).endsWith("/v1/permitted-profile")).map(([, options]) => options?.body)).toEqual([
      JSON.stringify({ tolerance: "aggressive" }), JSON.stringify({ tolerance: "moderate" }),
    ]);
  });
});
