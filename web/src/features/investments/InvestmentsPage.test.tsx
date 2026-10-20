import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { PersonaProvider } from "@/api/hooks";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { InvestmentsPage } from "./InvestmentsPage";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

const SYNCED = "2026-10-29T12:00:00-03:00";
const PASSWORD = "synthetic-fintual-password";
const link = { provider: "fintual", email: "m***@fintual-user.invalid", linked_at: SYNCED, synced_at: SYNCED, goals: 2, synthetic: true, relink_required: false };
const synced = {
  status: "OK", params_version: "inv-0.1", snapshot_id: "inv_1", as_of: SYNCED, facts: [],
  warnings: [{ code: "INVESTMENTS_AS_REPORTED", message: "As Fintual reported them.", must_mention: ["Fintual"] }],
  data: {
    provider: "fintual", currency: "CLP", source: "sync", as_of: "2026-10-29", synced_at: SYNCED, synthetic: true, stale: false,
    total_value: 2_079_570, total_deposited: 2_000_000, total_gain: 79_570, gain_pct: null,
    goals: [{ goal_id: "101", name: { untrusted_text: "Viaje" }, value: 1_264_350, deposited: 1_200_000, gain: 64_350 }],
    funds: [], contributions: null, documents: [], documents_agree: null,
  },
};
const holdings = { document_id: "invdoc_0000000000000001", provider: "fintual", kind: "holdings", as_of: "2026-10-14", imported_at: "2026-10-19T12:00:00-03:00", rows: 5, verified: true, issues: [] };
const movements = { ...holdings, document_id: "invdoc_0000000000000002", kind: "movements", as_of: "2026-09-15", rows: 11 };
const fromStatements = {
  status: "OK", params_version: "inv-0.1", snapshot_id: "invp_1", as_of: "2026-10-14", facts: [],
  warnings: [{ code: "INVESTMENTS_FROM_STATEMENT", message: "From the Fintual documents.", must_mention: ["Fintual"] }],
  data: {
    provider: "fintual", currency: "CLP", source: "statement", as_of: "2026-10-14", synced_at: null, synthetic: false, stale: false,
    total_value: 422_097, total_deposited: 372_333, total_gain: 49_764, gain_pct: 13.4,
    goals: [
      { goal_id: "goal_1", name: { untrusted_text: "Viaje a Japón" }, value: 285_073, deposited: 245_000, gain: 40_073 },
      { goal_id: "goal_2", name: { untrusted_text: "<b>Casa</b>" }, value: 80_509, deposited: 75_000, gain: 5_509 },
    ],
    funds: [{ fund_id: "risky_norris_a", fund: "Risky Norris", series: "A", shares: "62.7235", share_value: "4800.0000", value: 301_073 }],
    contributions: {
      first_day: "2025-11-03", last_day: "2026-09-15", contributions: 8, withdrawals: 1, contributed: 385_333, withdrawn: 13_000,
      net_contributed: 372_333, months: 11, active_months: 6, monthly_average: 35_030, last_contribution: "2026-09-15", complete: true,
    },
    documents: [holdings, movements], documents_agree: true,
  },
};
const step = (key: string, value: string | null) => ({ key, status: "done", value, by: null, confidence: null });
const ingested = (document: object, duplicate = false) => ({
  status: "OK", params_version: "inv-0.1", snapshot_id: "invdoc_1", as_of: SYNCED, facts: [], warnings: [],
  data: {
    kind: "investment", steps: [step("read", "pdf"), step("route", "investment")], statement: null, receipt: null, spending: null,
    investment: { document, duplicate, overview: null },
  },
});

interface Options { dataSource?: string; investments?: string; reject?: boolean; documents?: Record<string, unknown> }

/** A small stateful API: documents and the link exist once POSTed and are gone once DELETEd. Every request is recorded. */
function serve({ dataSource = "empty", investments = "fixture", reject = false, documents = {} }: Options = {}) {
  let linked = false;
  let imported = false;
  const requests: { path: string; method: string; body: unknown }[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body;
    requests.push({ path, method, body: typeof body === "string" ? JSON.parse(body) : body });
    if (path.endsWith("/health")) return json({ auth: "accounts", mode: "offline", investments });
    if (path.endsWith("/v1/me")) return json({ user_id: dataSource === "persona" ? "camila" : "usr_ana", data_source: dataSource, expires_at: "2026-10-30T00:00:00Z" });
    if (path.includes("/v1/documents") && method === "POST") {
      const answer = documents[(body as File).name] ?? ingested(holdings);
      if ((answer as { status: string }).status === "OK" && (answer as { data: { investment: { document: { verified: boolean } } } }).data.investment.document.verified) imported = true;
      return json(answer, (answer as { status: string }).status === "OK" ? 200 : 422);
    }
    if (path.endsWith("/v1/investments/documents") && method === "DELETE") {
      imported = false;
      return json({ removed: 2 });
    }
    if (path.endsWith("/v1/investments/link") && method === "POST") {
      if (reject) return json({ status: "ACCESS_REJECTED", link: null, field: null, message: "the provider did not accept these credentials" }, 422);
      linked = true;
      return json({ status: "LINKED", link, field: null, message: null }, 201);
    }
    if (path.endsWith("/v1/investments/link") && method === "DELETE") {
      linked = false;
      return json({ status: "UNLINKED", link: null, field: null, message: null });
    }
    if (path.endsWith("/v1/investments/link")) {
      return linked ? json({ status: "LINKED", link, field: null, message: null })
        : json({ status: "NOT_LINKED", link: null, field: null, message: "no investment account is linked" }, 404);
    }
    if (path.endsWith("/v1/investments/sync")) return json({ status: "SYNCED", link, field: null, message: null });
    if (path.endsWith("/v1/investments")) {
      if (imported) return json(fromStatements);
      if (linked) return json(synced);
      return json({ status: "INSUFFICIENT_DATA", params_version: "inv-0.1", missing: ["investment_account"], facts: [], warnings: [] }, 409);
    }
    return json({ status: "INSUFFICIENT_DATA", params_version: "fc-0.3", missing: ["financial data"], facts: [], warnings: [] }, 409);
  });
  return { spy, requests };
}

function Page() {
  const auth = useAuth();
  if (auth.pending) return <div role="status">Loading</div>;
  return <PersonaProvider><InvestmentsPage /></PersonaProvider>;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AuthProvider><Page /></AuthProvider></MemoryRouter></QueryClientProvider>);
}

const pdf = (name: string) => new File(["%PDF-1.7 synthetic"], name, { type: "application/pdf" });

async function upload(...files: File[]) {
  await userEvent.upload(await screen.findByLabelText("Choose files"), files);
}

async function openRealTime() {
  await userEvent.click(await screen.findByRole("radio", { name: "Real-time connection In development" }));
}

async function fillAndSubmit() {
  await userEvent.type(await screen.findByLabelText("Fintual email"), "mi.cuenta@fintual-user.invalid");
  await userEvent.type(screen.getByLabelText("Fintual password"), PASSWORD);
  const submit = screen.getByRole("button", { name: "Link Fintual" });
  expect(submit).toBeDisabled(); // consent first
  await userEvent.click(screen.getByLabelText(/I agree that Neural Ledger reads my Fintual goals/));
  expect(submit).toBeEnabled();
  await userEvent.click(submit);
}

describe("investments page: importing statements", () => {
  it("imports both documents one after the other and shows what the copilot now knows", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const { requests } = serve({ documents: { "certificado.pdf": ingested(movements) } });
    const { container } = renderPage();
    expect(await screen.findByRole("radio", { name: "Statements" })).toBeChecked();
    // Worded for any provider; the formats read today are named once, under the drop zone.
    expect(screen.getByRole("heading", { name: "Import your investment statements" })).toBeInTheDocument();
    expect(screen.getByText("Drop your investment statements here and the copilot will help you make sense of them")).toBeInTheDocument();
    expect(screen.getByText("Read today: Fintual. More providers soon.")).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);

    await upload(pdf("cartola.pdf"), pdf("certificado.pdf"));
    expect(await screen.findByText("cartola.pdf: Investment statement as of Oct 14, 2026")).toBeInTheDocument();
    expect(await screen.findByText("certificado.pdf: Transactions certificate up to Sep 15, 2026")).toBeInTheDocument();
    expect(screen.getByText("Verified: the figures add up (5 rows).")).toBeInTheDocument();
    const posts = requests.filter((r) => r.method === "POST" && r.path.includes("/v1/documents"));
    expect(posts).toHaveLength(2);
    expect(posts.every((r) => new URL(r.path, "http://x").searchParams.get("kind") === "investment")).toBe(true);
    expect(posts.map((r) => (r.body as File).name)).toEqual(["cartola.pdf", "certificado.pdf"]); // in the order given

    expect(await screen.findByText("CLP 422,097")).toBeInTheDocument();
    expect(screen.getByText("CLP +49,764")).toBeInTheDocument();
    expect(screen.getByText("13.4% of what you put in")).toBeInTheDocument();
    expect(screen.getByText(/you contributed CLP 385,333 in 8 contributions and withdrew CLP 13,000\. On average, CLP 35,030 a month/)).toBeInTheDocument();
    const funds = screen.getByRole("region", { name: "Funds" });
    expect(within(funds).getByRole("rowheader", { name: "Risky Norris A" })).toBeInTheDocument();
    expect(within(funds).getByText("62.7235")).toBeInTheDocument();
    const goals = screen.getByRole("region", { name: "Goals" });
    // A goal name is the user's text at Fintual: shown as text, never as markup.
    expect(within(goals).getByRole("rowheader", { name: "<b>Casa</b>" })).toBeInTheDocument();
    expect(within(goals).getByRole("rowheader", { name: "Viaje a Japón" })).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
  });

  it("explains a document that does not add up, in the interface language", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const unverified = { ...holdings, imported_at: null, verified: false, issues: [{ code: "TOTAL_MISMATCH", message: "the fund balances do not add up to the printed total" }] };
    serve({ documents: { "cartola.pdf": ingested(unverified) } });
    renderPage();
    await upload(pdf("cartola.pdf"));
    expect(await screen.findByText(/It could not be verified, so it was not kept: the fund balances do not add up to the total\./)).toBeInTheDocument();
    expect(screen.queryByText("Your investments")).not.toBeInTheDocument();
  });

  it("says when a file is not a statement it can read yet, and when it was already imported", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const unsupported = { status: "INVALID_INPUT", params_version: "inv-0.1", field: "file", allowed: ["investment_statement"], message: "this is not a document issued by Fintual", facts: [], warnings: [] };
    serve({ documents: { "boleta.pdf": unsupported, "otra-vez.pdf": ingested(holdings, true) } });
    renderPage();
    await upload(pdf("boleta.pdf"), pdf("otra-vez.pdf"));
    expect(await screen.findByText("The copilot cannot read this file as an investment statement yet. Today it reads Fintual's investment statement and transactions certificate.")).toBeInTheDocument();
    expect(await screen.findByText("Already imported; nothing changed.")).toBeInTheDocument();
  });

  it("keeps what it just read while the real-time tab is open", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    serve();
    renderPage();
    await upload(pdf("cartola.pdf"));
    const verified = await screen.findByText("Verified: the figures add up (5 rows).");
    expect(verified).toBeVisible();
    await openRealTime();
    expect(await screen.findByRole("region", { name: "Real-time connection" })).toBeInTheDocument();
    expect(verified).not.toBeVisible();
    await userEvent.click(screen.getByRole("radio", { name: "Statements" }));
    expect(verified).toBeVisible();
    expect(screen.queryByRole("region", { name: "Real-time connection" })).not.toBeInTheDocument();
  });

  it("refuses a file over 15 MB without sending it", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const { requests } = serve();
    renderPage();
    const big = pdf("enorme.pdf");
    Object.defineProperty(big, "size", { value: 16 * 1024 * 1024 });
    await upload(big);
    expect(await screen.findByText("The file is larger than 15 MB.")).toBeInTheDocument();
    expect(requests.some((r) => r.path.includes("/v1/documents"))).toBe(false);
  });

  it("deletes the imported documents only after a second confirmation", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const { requests } = serve();
    renderPage();
    await upload(pdf("cartola.pdf"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete imported documents" }));
    expect(requests.some((r) => r.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Delete documents" }));
    expect(await screen.findByText("Documents deleted. Nothing from them is kept.")).toBeInTheDocument();
    expect(requests.filter((r) => r.method === "DELETE" && r.path.endsWith("/v1/investments/documents"))).toHaveLength(1);
  });

  it("tells a demo persona that importing needs an account of its own", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const { requests } = serve({ dataSource: "persona" });
    renderPage();
    expect(await screen.findByText(/Your investments are imported from your own account/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose files")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Real-time connection/ })).not.toBeInTheDocument();
    expect(requests.some((r) => r.path.includes("/v1/investments") || r.path.includes("/v1/documents"))).toBe(false);
  });
});

describe("investments page: real-time connection, in development", () => {
  it("is a tab of its own, marked in development, that says what it is for and asks about a link only once opened", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const { requests } = serve();
    const { container } = renderPage();
    const tab = await screen.findByRole("radio", { name: "Real-time connection In development" });
    expect(tab).not.toBeChecked();
    expect(screen.queryByRole("region", { name: "Real-time connection" })).not.toBeInTheDocument();
    expect(requests.some((r) => r.path.endsWith("/v1/investments/link"))).toBe(false);

    await userEvent.click(tab);
    const live = await screen.findByRole("region", { name: "Real-time connection" });
    expect(within(live).getByText("In development")).toBeInTheDocument();
    expect(within(live).getByText(/^The goal: link your investment accounts once/)).toBeInTheDocument();
    expect(within(live).getByText("Why it is not available yet")).toBeInTheDocument();
    expect(within(live).getByText("A preview of the form: it stays disabled until the connection is ready.")).toBeInTheDocument();
    expect(await within(live).findByLabelText("Fintual email")).toBeDisabled();
    expect(within(live).getByLabelText("Fintual password")).toBeDisabled();
    expect(within(live).getByRole("button", { name: "Link Fintual" })).toBeDisabled();
    expect(within(live).queryByText("Sandbox: this links a synthetic account")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Import your investment statements" })).not.toBeInTheDocument();
    expect(requests.some((r) => r.method === "POST" && r.path.endsWith("/v1/investments/link"))).toBe(false);
    expect((await axe(container)).violations).toEqual([]);
  });

  it("lists ten or more providers, the most used in China among them, and only Fintual can be chosen", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    serve();
    renderPage();
    await openRealTime();
    const select = await screen.findByLabelText("Provider");
    const options = within(select).getAllByRole("option") as HTMLOptionElement[];
    expect(options.length).toBeGreaterThanOrEqual(10);
    expect((select as HTMLSelectElement).value).toBe("fintual");
    expect(options.filter((option) => !option.disabled).map((option) => option.value)).toEqual(["fintual"]);
    for (const china of ["Alipay (Ant Fortune)", "WeChat Pay (Licaitong)", "Tiantian Fund", "East Money", "Futu (moomoo)", "Tiger Brokers"]) {
      expect(within(select).getByRole("option", { name: `${china} (available in the future)` })).toBeDisabled();
    }
    expect(within(select).getByRole("group", { name: "China" })).toBeInTheDocument();
  });

  it("with the development flag on, links with explicit consent and sends the password once", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    vi.stubEnv("VITE_INVESTMENT_LINKING", "on");
    const { requests } = serve();
    const { container } = renderPage();
    await openRealTime();
    expect(await screen.findByText("Sandbox: this links a synthetic account")).toBeInTheDocument();
    await fillAndSubmit();
    const post = requests.find((r) => r.method === "POST" && r.path.endsWith("/v1/investments/link"));
    expect(post?.body).toEqual({ email: "mi.cuenta@fintual-user.invalid", password: PASSWORD, consent: true });
    expect(await screen.findByText("Fintual account m***@fintual-user.invalid")).toBeInTheDocument();
    expect(screen.queryByLabelText("Fintual password")).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(PASSWORD);
    expect((await axe(container)).violations).toEqual([]);

    // What the copilot now knows is on the statements tab, whatever its source.
    await userEvent.click(screen.getByRole("radio", { name: "Statements" }));
    expect(await screen.findByText("CLP 2,079,570")).toBeVisible();

    await openRealTime();
    await userEvent.click(await screen.findByRole("button", { name: "Unlink" }));
    expect(requests.some((r) => r.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Unlink and delete what was synced" }));
    expect(await screen.findByText("Account unlinked. Nothing from it is kept.")).toBeInTheDocument();
  });

  it("with the development flag on, explains a refused password and keeps nothing the user typed", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    vi.stubEnv("VITE_INVESTMENT_LINKING", "on");
    serve({ reject: true, investments: "fintual" });
    const { container } = renderPage();
    await openRealTime();
    expect(await screen.findByText("Your Fintual email and password go to Fintual")).toBeInTheDocument();
    await fillAndSubmit();
    expect(await screen.findByText("Fintual did not accept that email and password.")).toBeInTheDocument();
    expect(screen.getByLabelText("Fintual password")).toHaveValue("");
    expect(container.innerHTML).not.toContain(PASSWORD);
    await waitFor(() => expect(screen.getByRole("button", { name: "Link Fintual" })).toBeDisabled());
  });
});
