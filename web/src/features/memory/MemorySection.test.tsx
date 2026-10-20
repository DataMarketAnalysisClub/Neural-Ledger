import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { axe } from "vitest-axe";
import { PersonaProvider } from "@/api/hooks";
import { MemorySection } from "./MemorySection";

afterEach(() => { vi.restoreAllMocks(); });

const declaration = (version: number, amount: number, month: string) => ({
  memory_id: `mem_${version}`, chain_id: "chn_1", version, catalog_version: "mem-0.1",
  value: { type: "salary_net", salary_net: { amount, net: true, effective_from: month } },
  confirmed_at: "2026-10-20T12:00:00Z", confirmed_by: "user", source: "profile", origin: { kind: "profile" }, audit_ref: `evt_${version}`,
});

/** A tiny memory backend: the component only ever learns what the API answers. */
function backend(initial: { consent: string; items: unknown[] }) {
  const state = { ...initial };
  const calls: { method: string; path: string; body?: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = new URL(String(url), "http://x").pathname.replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
    const view = () => ({ catalog_version: "mem-0.1", ...state });
    if (path === "/v1/memory" && method === "GET") return json(view());
    if (path === "/v1/memory/consent" && method === "PUT") {
      state.consent = body.consent;
      return json({ consent: body.consent, consent_generation: 2, memory_revision: 1, changed: true });
    }
    if (path === "/v1/profile/income") {
      if (state.consent !== "granted") return json({ status: "CONSENT_REQUIRED", message: "memory consent required" }, 428);
      if (body.expected_version !== 1) return json({ status: "VERSION_CONFLICT", message: "x" }, 409);
      state.items = [{ chain_id: "chn_1", type: "salary_net", versions: 2, current: declaration(2, body.salary_net.amount, body.salary_net.effective_from), upcoming: null, check: { status: "declared" } }];
      return json(view());
    }
    if (path === "/v1/memory/export") return json({ catalog_version: "mem-0.1", declarations: [declaration(1, 1_000_000, "2026-01")] });
    if (path === "/v1/memory/chn_1" && method === "DELETE") {
      state.items = [];
      return json({ chain_id: "chn_1", deleted_versions: 1, revoked_proposals: 0 });
    }
    return json({ status: "NOT_FOUND", message: "not found" }, 404);
  });
  return calls;
}

function renderSection(persona = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PersonaProvider>
        <MemorySection persona={persona} />
      </PersonaProvider>
    </QueryClientProvider>,
  );
}

const verified = { chain_id: "chn_1", type: "salary_net", versions: 1, current: declaration(1, 1_000_000, "2026-01"), upcoming: null, check: { status: "verified" } };

describe("MemorySection", () => {
  it("shows the salary with saved-only wording by its evidence, and is accessible", async () => {
    backend({ consent: "granted", items: [verified] });
    const { container } = renderSection();
    expect(await screen.findByText("CLP 1,000,000")).toBeVisible();
    expect(screen.getByText("Saved and checked against your statements; it does not change your projections.")).toBeVisible();
    expect(screen.getByText("Memory is on")).toBeVisible();
    expect((await axe(container)).violations).toEqual([]);
  });

  it("lists declarations without consent but checks and edits nothing", async () => {
    backend({ consent: "revoked", items: [{ ...verified, check: null }] });
    renderSection();
    expect(await screen.findByText("Saved. With memory off it is not checked or used.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Change salary" })).toBeNull();
    expect(screen.getByRole("button", { name: "Export my memory" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete my salary" })).toBeEnabled();
  });

  it("turns memory on and off through the API only", async () => {
    const calls = backend({ consent: "missing", items: [] });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Turn memory on" }));
    await waitFor(() => expect(calls).toContainEqual({ method: "PUT", path: "/v1/memory/consent", body: { consent: "granted" } }));
    expect(await screen.findByRole("button", { name: "Turn memory off" })).toBeVisible();
  });

  it("edits through a new version with the head as expected_version", async () => {
    const calls = backend({ consent: "granted", items: [verified] });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Change salary" }));
    const form = screen.getByRole("form", { name: "Change salary" });
    await userEvent.type(within(form).getByLabelText("Net salary (CLP)"), "1.300.000");
    await userEvent.type(within(form).getByLabelText("From the pay month"), "2026-12");
    await userEvent.click(within(form).getByRole("button", { name: "Save salary" }));
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT", path: "/v1/profile/income", body: { salary_net: { amount: 1_300_000, net: true, effective_from: "2026-12" }, expected_version: 1 },
      }),
    );
    expect(await screen.findByText(/Saved as a new version/)).toBeVisible();
    expect(await screen.findByText("CLP 1,300,000")).toBeVisible();
  });

  it("deletes the whole chain in two steps", async () => {
    const calls = backend({ consent: "revoked", items: [verified] });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Delete my salary" }));
    expect(screen.getByText(/This cannot be undone/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Delete every version" }));
    expect(await screen.findByText("Deleted 1 versions.")).toBeVisible();
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([{ method: "DELETE", path: "/v1/memory/chn_1", body: undefined }]);
    expect(await screen.findByText("You have not declared a salary.")).toBeVisible();
  });

  it("exports every version as a download", async () => {
    backend({ consent: "missing", items: [verified] });
    const created = vi.fn(() => "blob:memory");
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Export my memory" }));
    expect(await screen.findByText("Downloaded 1 versions.")).toBeVisible();
    expect(created).toHaveBeenCalledOnce() ;
    expect(click).toHaveBeenCalledOnce();
  });

  it("tells a shared persona it keeps no memory and asks the API nothing", () => {
    const calls = backend({ consent: "missing", items: [] });
    renderSection(true);
    expect(screen.getByText("The shared demo profile keeps no memory.")).toBeVisible();
    expect(calls).toEqual([]);
  });
});
