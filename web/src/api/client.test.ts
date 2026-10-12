import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError, request, requestEnvelope } from "./client";
import { describeError } from "@/components/ui";

function respond(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

afterEach(() => vi.restoreAllMocks());

describe("request", () => {
  it("names the persona on every call", async () => {
    const spy = respond(200, { ok: true });
    await request("/health", { user: "diego" });
    const init = spy.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-User-Id"]).toBe("diego");
  });

  it("turns a 422 envelope into an error that points at the field", async () => {
    respond(422, { status: "INVALID_INPUT", field: "installments", allowed: ["3", "6", "12", "18", "24"], message: "installments must be one of 3, 6, 12, 18, 24", facts: [], warnings: [] });
    const error = await requestEnvelope("/v1/simulate-purchase", { user: "camila", method: "POST", body: {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail.field).toBe("installments");
    expect(describeError(error)).toContain("installments must be one of");
  });

  it("describes missing data for a 409", async () => {
    respond(409, { status: "INSUFFICIENT_DATA", missing: ["income"], facts: [], warnings: [] });
    const error = await requestEnvelope("/v1/forecast", { user: "camila" }).catch((e) => e);
    expect(describeError(error)).toContain("Missing: income");
  });

  it("keeps the blocked outcome of a 403 for the verdict banner", async () => {
    respond(403, { status: "BLOCKED", reason: "AUTHORIZATION_REPLAYED", authorized_amount: null, requested_amount: null });
    const error = await request("/v1/actions/execute", { user: "camila", method: "POST", body: { authorization_id: "auth_1" } }).catch((e) => e);
    expect((error as ApiError).httpStatus).toBe(403);
    expect((error as ApiError).detail.reason).toBe("AUTHORIZATION_REPLAYED");
  });

  it("reports an unreachable API as a network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await request("/health", { user: "camila" }).catch((e) => e);
    expect(error).toBeInstanceOf(NetworkError);
    expect(describeError(error)).toContain("port 8000");
  });
});
