import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { PersonaProvider, useImportStatement, usePersona, useSetCategory, useStatements, useTransactions } from "./hooks";

/** A stand-in for the HTTP API: it records every request and keeps statements per owner, as the backend does. */
interface Sent {
  readonly path: string;
  readonly method: string;
  readonly init: RequestInit;
}

let mode: "demo" | "accounts";
let signedIn: string | null;
let sent: Sent[];
let owned: Map<string, number>;
let relabeled: string | null;

const ok = (data: unknown) => ({ status: "OK", params_version: "st-0.1", facts: [], warnings: [], data });
const reply = (status: number, body: unknown) => new Response(body === null ? null : JSON.stringify(body), { status });
const statement = (owner: string, n: number) => ({ statement_id: `stmt_${owner}_${n}`, bank: "santander_cl_cuentacorriente_xlsx", account_ref: "****3456" });

function serve(input: RequestInfo | URL, init: RequestInit = {}): Response {
  const path = new URL(String(input), "http://localhost").pathname;
  const method = init.method ?? "GET";
  sent.push({ path, method, init });
  const headers = (init.headers ?? {}) as Record<string, string>;
  const owner = mode === "accounts" ? signedIn : (headers["X-User-Id"] ?? null);
  if (path === "/api/health") {
    return reply(200, { status: "ok", auth: mode, mode: "offline", language_model: "fake", decision_chain: [], params_version: "p", audit_chain_ok: true, tools: [] });
  }
  if (path === "/api/v1/auth/signin") {
    signedIn = (JSON.parse(String(init.body)) as { email: string }).email.startsWith("second") ? "usr_second" : "usr_first";
    return reply(200, { user_id: signedIn, expires_at: "2026-10-16T08:00:00Z" });
  }
  if (path === "/api/v1/auth/signout") {
    signedIn = null;
    return reply(204, null);
  }
  if (!owner) return reply(401, { status: "UNAUTHENTICATED", message: "authentication required" });
  if (path === "/api/v1/me") return reply(200, { user_id: owner, data_source: "empty", expires_at: "2026-10-16T08:00:00Z" });
  if (path === "/api/v1/statements" && method === "POST") {
    const count = (owned.get(owner) ?? 0) + 1;
    owned.set(owner, count);
    return reply(200, ok({ imports: [{ duplicate: false, statement: statement(owner, count), redaction: null, ledger: { posted: 1, new: 1, uncategorized: 0, classifier: "x" } }] }));
  }
  if (path === "/api/v1/statements") {
    return reply(200, ok(Array.from({ length: owned.get(owner) ?? 0 }, (_, i) => statement(owner, i + 1))));
  }
  if (path.startsWith("/api/v1/transactions/") && method === "PATCH") {
    const { category } = JSON.parse(String(init.body)) as { category: string };
    relabeled = category;
    return reply(200, ok({ txn_id: path.split("/").pop(), category, classifier: "user", confidence: null }));
  }
  if (path === "/api/v1/transactions") {
    return reply(200, ok({ transactions: [{ txn_id: "txn_1", category: relabeled ?? "other" }], spending: [], income: [] }));
  }
  return reply(404, { detail: "Not Found" });
}

const file = new Blob(["synthetic statement bytes"]);

function Probe() {
  const auth = useAuth();
  const { identity } = usePersona();
  const statements = useStatements();
  const importer = useImportStatement();
  return (
    <div>
      <p>identity {identity.user_id}</p>
      <p>{statements.data ? `statements ${statements.data.data?.length ?? 0}` : "statements loading"}</p>
      <button type="button" onClick={() => importer.mutate(file)}>import</button>
      {auth.mode === "accounts" && <button type="button" onClick={() => void auth.signout()}>sign out</button>}
    </div>
  );
}

function Gate() {
  const auth = useAuth();
  if (auth.pending) return <p>pending</p>;
  if (auth.mode === "accounts" && !auth.me) {
    return <button type="button" onClick={() => void auth.signin({ email: "second@example.invalid", password: "synthetic-password" })}>sign in second</button>;
  }
  return <PersonaProvider key={auth.me?.user_id ?? "demo"}><Probe /></PersonaProvider>;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><AuthProvider><Gate /></AuthProvider></QueryClientProvider>);
  return client;
}

beforeEach(() => {
  vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
  sent = [];
  owned = new Map();
  relabeled = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => serve(input, init));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("statement hooks in accounts mode", () => {
  it("read and import under the signed-in account with its cookie, never the demo persona header", async () => {
    mode = "accounts";
    signedIn = "usr_first";
    const client = mount();
    await waitFor(() => expect(screen.getByText("statements 0")).toBeInTheDocument());
    expect(screen.getByText("identity usr_first")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "import" }));
    await waitFor(() => expect(screen.getByText("statements 1")).toBeInTheDocument());

    const upload = sent.find((s) => s.path === "/api/v1/statements" && s.method === "POST");
    expect(upload?.init.body).toBe(file);
    expect(upload?.init.headers).toEqual({ "Content-Type": "application/octet-stream" });
    for (const { init } of sent) {
      expect(init.credentials).toBe("same-origin");
      expect(init.headers).not.toHaveProperty("X-User-Id");
    }
    const keys = client.getQueryCache().findAll({ queryKey: ["usr_first", "statements"] });
    expect(keys).toHaveLength(1);
    expect(client.getQueryCache().findAll({ queryKey: ["camila"] })).toHaveLength(0);
  });

  it("drops the previous account's statements on an account change and shows the next one only its own", async () => {
    mode = "accounts";
    signedIn = "usr_first";
    const client = mount();
    await waitFor(() => expect(screen.getByText("statements 0")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "import" }));
    await waitFor(() => expect(screen.getByText("statements 1")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "sign out" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "sign in second" })).toBeInTheDocument());
    expect(client.getQueryCache().findAll({ queryKey: ["usr_first"] })).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "sign in second" }));
    await waitFor(() => expect(screen.getByText("identity usr_second")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("statements 0")).toBeInTheDocument());
    expect(client.getQueryCache().findAll({ queryKey: ["usr_first"] })).toHaveLength(0);
    expect(owned.get("usr_first")).toBe(1);
  });
});

describe("statement hooks in demo mode", () => {
  it("import under the selected persona's header", async () => {
    mode = "demo";
    signedIn = null;
    mount();
    await waitFor(() => expect(screen.getByText("statements 0")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "import" }));
    await waitFor(() => expect(screen.getByText("statements 1")).toBeInTheDocument());

    const upload = sent.find((s) => s.path === "/api/v1/statements" && s.method === "POST");
    expect(upload?.init.body).toBe(file);
    expect(upload?.init.headers).toEqual({ "X-User-Id": "camila", "Content-Type": "application/octet-stream" });
    expect(owned.get("camila")).toBe(1);
  });
});

function CategoryProbe() {
  const transactions = useTransactions();
  const setCategory = useSetCategory();
  const first = transactions.data?.data?.transactions[0];
  return (
    <div>
      <p>{first ? `category ${first.category}` : "transactions loading"}</p>
      <button type="button" onClick={() => setCategory.mutate({ txnId: "txn_1", category: "movement" })}>mark movement</button>
    </div>
  );
}

describe("category hook", () => {
  it("sends the user's category as a PATCH under the persona and re-reads the ledger from the API", async () => {
    mode = "demo";
    signedIn = null;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><AuthProvider><PersonaProvider><CategoryProbe /></PersonaProvider></AuthProvider></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText("category other")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "mark movement" }));
    await waitFor(() => expect(screen.getByText("category movement")).toBeInTheDocument());

    const patch = sent.find((s) => s.method === "PATCH");
    expect(patch?.path).toBe("/api/v1/transactions/txn_1");
    expect(patch?.init.headers).toEqual({ "X-User-Id": "camila", "Content-Type": "application/json" });
    expect(JSON.parse(String(patch?.init.body))).toMatchObject({ category: "movement" });
    expect(sent.filter((s) => s.path === "/api/v1/transactions")).toHaveLength(2); // shown only after the API answered
  });
});

function SessionProbe() {
  const { persona, sessionId, newSession, setPersona } = usePersona();
  return (
    <>
      <output aria-label="session">{sessionId}</output>
      <button onClick={newSession}>new</button>
      <button onClick={() => setPersona(persona === "camila" ? "diego" : "camila")}>switch</button>
    </>
  );
}

function renderProbe() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PersonaProvider>
        <SessionProbe />
      </PersonaProvider>
    </QueryClientProvider>,
  );
}

const session = () => screen.getByLabelText("session").textContent;

describe("PersonaProvider sessions", () => {
  beforeEach(() => sessionStorage.clear());

  it("keeps one session per persona and tab, and newSession replaces it", async () => {
    renderProbe();
    const first = session();
    expect(first).toMatch(/^ui-camila-/);
    expect(sessionStorage.getItem("nl.session.camila")).toBe(first);

    await userEvent.click(screen.getByText("new"));
    const second = session();
    expect(second).toMatch(/^ui-camila-/);
    expect(second).not.toBe(first);
    expect(sessionStorage.getItem("nl.session.camila")).toBe(second);

    await userEvent.click(screen.getByText("switch"));
    expect(session()).toMatch(/^ui-diego-/);
    await userEvent.click(screen.getByText("switch"));
    expect(session()).toBe(second); // back to Camila's current conversation, not a new one
  });
});
