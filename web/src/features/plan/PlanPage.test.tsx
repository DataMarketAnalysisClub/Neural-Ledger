import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { PersonaProvider, usePersona } from "@/api/hooks";
import type { PersonaId } from "@/api/client";
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

afterEach(() => vi.restoreAllMocks());

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
});
