/**
 * Thin HTTP client for the Neural Ledger API. It moves JSON and tells the UI which state it is in;
 * it never computes money. Demo requests name a persona; accounts use same-origin cookies.
 */
import type { Envelope as RawEnvelope, Fact, Caveat } from "@/contracts/common/envelope";
import type { ActionOutcome, ActionTerms } from "@/contracts/actions/action_outcome";
import type { ChatReply } from "@/contracts/chat/chat_reply";
import type { AuditEvent } from "@/contracts/audit/audit_event";

export type { Fact, Caveat, ActionOutcome, ActionTerms, ChatReply, AuditEvent };

/** An envelope whose `data` is typed by the endpoint. */
export type Envelope<T> = Omit<RawEnvelope, "data"> & { data?: T | null };

export const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

export type PersonaId = "camila" | "diego";
export type ApiIdentity =
  | { readonly kind: "demo"; readonly user_id: PersonaId }
  | { readonly kind: "accounts"; readonly user_id: string };

export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("network");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

/** An API answer that is not a usable success (422, 409, 403, 502...). The body is kept for display. */
export class ApiError extends Error {
  constructor(
    readonly httpStatus: number,
    readonly body: unknown,
  ) {
    super(`HTTP ${httpStatus}`);
    this.name = "ApiError";
  }
  /** The envelope or action-outcome fields the UI shows. */
  get detail(): { status?: string; field?: string | null; allowed?: string[]; message?: string | null; missing?: string[]; reason?: string | null } {
    return (this.body && typeof this.body === "object" ? this.body : {}) as never;
  }
}

interface RequestOptions {
  user?: PersonaId;
  identity?: ApiIdentity;
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
}

export async function request<T>(path: string, { user, identity, method = "GET", body, query }: RequestOptions = {}): Promise<T> {
  const qs = query
    ? "?" +
      Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  if (import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true") {
    const { mockRequest } = await import("./mockAccounts");
    return (await mockRequest(path, { method, body, query })) as T;
  }
  // A file (statement import) travels as the raw body; the server reads the bytes, not the Content-Type.
  const raw = body instanceof Blob;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}${qs === "?" ? "" : qs}`, {
      method,
      credentials: "same-origin",
      headers: {
        ...(identity?.kind === "demo" || (!identity && user) ? { "X-User-Id": identity?.user_id ?? user } : {}),
        ...(body !== undefined ? { "Content-Type": raw ? "application/octet-stream" : "application/json" } : {}),
      },
      body: raw ? body : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    throw new NetworkError(cause);
  }
  const text = await response.text();
  let parsed: unknown;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }
  if (!response.ok) throw new ApiError(response.status, parsed);
  return parsed as T;
}

/** Envelopes come back with HTTP 200 for OK and 422/409 otherwise; a non-OK envelope is an ApiError. */
export async function requestEnvelope<T>(path: string, opts: RequestOptions): Promise<Envelope<T>> {
  const envelope = await request<Envelope<T>>(path, opts);
  if (envelope.status !== "OK") throw new ApiError(200, envelope);
  return envelope;
}

/** Look up a fact by key. Facts carry the unit, so the currency always comes from the engine. */
export function fact(envelope: { facts: Fact[] } | undefined, key: string): Fact | undefined {
  return envelope?.facts.find((f) => f.key === key);
}
