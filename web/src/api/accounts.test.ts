import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./client";
import { accountsApi } from "./accounts";

beforeEach(() => vi.stubEnv("VITE_ACCOUNTS_MOCK", "true"));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("accounts request identity", () => {
  it("sends same-origin cookies without the demo identity header", async () => {
    vi.stubEnv("VITE_ACCOUNTS_MOCK", "false");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "OK" }), { status: 200 }));

    await request("/v1/profile", { identity: { kind: "accounts", user_id: "camila" } });

    const init = fetch.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("same-origin");
    expect(init?.headers).not.toHaveProperty("X-User-Id");
  });
});

describe("local accounts mock", () => {
  it("returns a profile with synthetic provenance in a complete OK envelope", async () => {
    await accountsApi.signup({ email: "provenance@example.invalid", password: "synthetic-password-four", display_name: "Mock Tester" });

    const profile = await accountsApi.profile();

    expect(profile).toMatchObject({
      status: "OK",
      params_version: expect.stringMatching(/^mock-/),
      snapshot_id: expect.stringMatching(/^mock:accounts:/),
      as_of: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/),
      facts: [],
      warnings: [],
      data: {
        user_id: expect.stringMatching(/^usr_/),
        display_name: { untrusted_text: "Mock Tester" },
        language: "en",
        declared_tolerance: null,
        questionnaire_version: null,
        questionnaire: [],
      },
    });
  });

  it("answers a domain-rejected profile edit with an INVALID_INPUT envelope naming the field", async () => {
    await accountsApi.signup({ email: "invalid-name@example.invalid", password: "synthetic-password-five", display_name: "Valid Tester" });

    const failure = await accountsApi.updateProfile({ display_name: "123", language: "en" }).then(() => null, (error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    if (failure instanceof ApiError) {
      expect(failure.httpStatus).toBe(422);
      expect(failure.body).toEqual({
        status: "INVALID_INPUT", params_version: expect.stringMatching(/^mock-/), field: "display_name", allowed: [], message: expect.any(String), facts: [], warnings: [],
      });
    }
    expect((await accountsApi.profile()).data?.display_name.untrusted_text).toBe("Valid Tester");
  });

  it("answers an empty profile-edit body with the strict auth error on field body", async () => {
    await accountsApi.signup({ email: "empty-edit@example.invalid", password: "synthetic-password-five", display_name: "Valid Tester" });

    const failure = await request("/v1/profile", { method: "PUT", body: {} }).then(() => null, (error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    if (failure instanceof ApiError) {
      expect(failure.httpStatus).toBe(422);
      expect(failure.body).toEqual({ status: "INVALID_INPUT", field: "body", message: expect.any(String) });
    }
  });

  it("returns only the contracted session and me fields, with one absolute expiry", async () => {
    const session = await accountsApi.signup({ email: "shape@example.invalid", password: "synthetic-password", display_name: "Shape Tester", language: "es" });

    const me = await accountsApi.me();
    const profile = await accountsApi.profile();

    expect(session).toEqual({ user_id: me.user_id, expires_at: expect.any(String) });
    expect(me).toEqual({ user_id: session.user_id, data_source: "empty", expires_at: session.expires_at });
    expect(Date.parse(session.expires_at)).toBeGreaterThan(Date.now());
    expect(profile.data?.language).toBe("es");
  });

  it.each([
    { flow: "signup", issue: () => accountsApi.signup({ email: "ttl-signup@example.invalid", password: "synthetic-password", display_name: "TTL Tester" }) },
    { flow: "signin", issue: async () => {
      await accountsApi.signup({ email: "ttl-signin@example.invalid", password: "synthetic-password", display_name: "Returning Tester" });
      await accountsApi.signout();
      vi.setSystemTime(new Date("2026-10-14T14:00:00Z"));
      return accountsApi.signin({ email: "ttl-signin@example.invalid", password: "synthetic-password" });
    } },
    { flow: "demo-session", issue: () => accountsApi.demoSession("camila") },
  ])("keeps $flow valid until 12 hours after issuance without sliding on me reads", async ({ issue }) => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-10-14T12:00:00Z"));
      const session = await issue();
      const issuedAt = Date.now();

      expect(session.expires_at).toBe(new Date(issuedAt + 12 * 60 * 60 * 1000).toISOString());
      vi.setSystemTime(new Date(issuedAt + 6 * 60 * 60 * 1000));
      expect(await accountsApi.me()).toMatchObject({ user_id: session.user_id, expires_at: session.expires_at });
      vi.setSystemTime(new Date(issuedAt + (11 * 60 + 59) * 60 * 1000));
      expect(await accountsApi.me()).toMatchObject({ user_id: session.user_id, expires_at: session.expires_at });
      expect(await accountsApi.me()).toMatchObject({ expires_at: session.expires_at });
      vi.setSystemTime(new Date(issuedAt + 12 * 60 * 60 * 1000));
      await expect(accountsApi.me()).rejects.toMatchObject({ httpStatus: 401, body: { status: "UNAUTHENTICATED" } });
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps authentication failures generic and uses the strict error statuses", async () => {
    await accountsApi.signup({ email: "duplicate@example.invalid", password: "synthetic-password", display_name: "Duplicate Tester" });

    const duplicate = await accountsApi.signup({ email: "duplicate@example.invalid", password: "synthetic-password", display_name: "Duplicate Tester" }).then(() => null, (error: unknown) => error);
    const missing = await accountsApi.signin({ email: "missing@example.invalid", password: "wrong-password" }).then(() => null, (error: unknown) => error);
    const malformed = await accountsApi.signin({ email: "malformed", password: "wrong-password" }).then(() => null, (error: unknown) => error);

    expect(duplicate).toBeInstanceOf(ApiError);
    expect(missing).toBeInstanceOf(ApiError);
    expect(malformed).toBeInstanceOf(ApiError);
    if (duplicate instanceof ApiError && missing instanceof ApiError && malformed instanceof ApiError) {
      expect(duplicate.httpStatus).toBe(409);
      expect(duplicate.body).toEqual({ status: "EMAIL_TAKEN", message: expect.any(String), field: "email" });
      expect(missing.httpStatus).toBe(401);
      expect(missing.body).toEqual({ status: "INVALID_CREDENTIALS", message: expect.any(String) });
      expect(malformed.body).toEqual(missing.body);
      expect(JSON.stringify([duplicate.body, missing.body])).not.toContain("@example.invalid");
    }
  });

  it("reissues only a session receipt on signin", async () => {
    const created = await accountsApi.signup({ email: "returning@example.invalid", password: "synthetic-password", display_name: "Returning Tester" });
    await accountsApi.signout();

    const returned = await accountsApi.signin({ email: "returning@example.invalid", password: "synthetic-password" });
    const me = await accountsApi.me();

    expect(returned).toEqual({ user_id: created.user_id, expires_at: expect.any(String) });
    expect(me.expires_at).toBe(returned.expires_at);
  });

  it("returns no signout body and revokes the mock session", async () => {
    await accountsApi.signup({ email: "signout@example.invalid", password: "synthetic-password", display_name: "Signout Tester" });

    const signedOut = await accountsApi.signout();

    expect(signedOut).toBeNull();
    await expect(accountsApi.me()).rejects.toMatchObject({ httpStatus: 401 });
  });

  it("accepts a single profile-update field without changing the other", async () => {
    await accountsApi.signup({ email: "partial@example.invalid", password: "synthetic-password", display_name: "First Name" });

    await accountsApi.updateProfile({ language: "es" });

    const profile = await accountsApi.profile();
    expect(profile.data?.display_name.untrusted_text).toBe("First Name");
    expect(profile.data?.language).toBe("es");
  });

  it("reports missing financial data without manufacturing a successful state", async () => {
    await accountsApi.signup({ email: "no-finance@example.invalid", password: "synthetic-password-six", display_name: "Empty Tester" });

    const state = request("/v1/state");

    await expect(state).rejects.toMatchObject({
      httpStatus: 409,
      body: { status: "INSUFFICIENT_DATA", params_version: expect.stringMatching(/^mock-/), missing: ["financial data"], facts: [], warnings: [] },
    });
  });

  it("keeps a new account empty and scopes profiles across sessions", async () => {
    await accountsApi.signup({ email: "empty-one@example.invalid", password: "synthetic-password-one", display_name: "First Tester" });
    const first = await accountsApi.profile();
    await accountsApi.signout();

    await accountsApi.signup({ email: "empty-two@example.invalid", password: "synthetic-password-two", display_name: "Second Tester" });
    const second = await accountsApi.profile();

    expect(first.data?.display_name.untrusted_text).toBe("First Tester");
    expect(first.data?.declared_tolerance).toBeNull();
    expect(second.data?.user_id).not.toBe(first.data?.user_id);
    expect(second.data?.display_name.untrusted_text).toBe("Second Tester");
    expect(second.data?.questionnaire).toEqual([]);
  });

  it("derives the cap from submitted versioned answers in the mock, not from a client verdict", async () => {
    await accountsApi.signup({ email: "scores@example.invalid", password: "synthetic-password-three", display_name: "Scores Tester" });
    const definition = await accountsApi.questionnaire();

    await accountsApi.submitQuestionnaire({
      version: definition.data?.version ?? "",
      answers: (definition.data?.questions ?? []).map((question) => ({
        question_id: question.question_id,
        option_id: question.options[question.question_id === "tight_month" ? 0 : 2]?.option_id ?? "",
      })),
    });

    const profile = await accountsApi.profile();
    expect(profile.data?.declared_tolerance).toBe("moderate");
    expect(profile.data?.questionnaire_version).toBe("pq-0.1");
    expect(profile.data?.questionnaire).toHaveLength(5);
  });

  it("renders persona metadata and permitted capacity without treating it as sample data", async () => {
    const session = await accountsApi.demoSession("camila");

    const me = await accountsApi.me();
    const permitted = await accountsApi.permitted("aggressive");

    expect(session).toEqual({ user_id: "camila", expires_at: expect.any(String) });
    expect(me).toEqual({ user_id: "camila", data_source: "persona", expires_at: session.expires_at });
    expect(permitted.data).toEqual({ tolerance: "aggressive", capacity: "conservative", permitted: "conservative", hard_rules_triggered: [] });
  });

  it("rejects a write to a read-only persona profile with a strict auth error", async () => {
    await accountsApi.demoSession("diego");
    const definition = await accountsApi.questionnaire();

    await expect(accountsApi.updateProfile({ display_name: "Altered", language: "en" })).rejects.toMatchObject({
      httpStatus: 403, body: { status: "PROFILE_READ_ONLY", message: expect.any(String) },
    });
    const error = await accountsApi.submitQuestionnaire({
      version: definition.data?.version ?? "",
      answers: (definition.data?.questions ?? []).map((question) => ({ question_id: question.question_id, option_id: question.options[0]?.option_id ?? "" })),
    }).then(() => null, (failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) expect(error.body).toEqual({ status: "PROFILE_READ_ONLY", message: expect.any(String) });
    expect((await accountsApi.profile()).data?.display_name.untrusted_text).toBe("Diego");
  });

  it("offers no sample-data action: the API has no such method and the mock serves no such route", async () => {
    await accountsApi.signup({ email: "no-sample@example.invalid", password: "synthetic-password-seven", display_name: "Empty Tester" });

    const attempt = await request("/v1/profile/sample-data", { method: "POST" }).then(() => null, (error: unknown) => error);

    expect(Object.keys(accountsApi).some((name) => /sample/i.test(name))).toBe(false);
    expect(attempt).toBeInstanceOf(ApiError);
    if (attempt instanceof ApiError) expect(attempt.httpStatus).toBe(404);
    expect(await accountsApi.me()).toMatchObject({ data_source: "empty" });
    await expect(accountsApi.permitted("conservative")).rejects.toMatchObject({
      httpStatus: 409, body: { status: "INSUFFICIENT_DATA", missing: ["financial data"] },
    });
  });

  it("rejects an expired persona session without returning a prior profile", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-10-14T12:00:00Z"));
      const session = await accountsApi.demoSession("diego");

      vi.setSystemTime(new Date(session.expires_at));

      await expect(accountsApi.me()).rejects.toMatchObject({
        httpStatus: 401, body: { status: "UNAUTHENTICATED", message: expect.any(String) },
      });
      await expect(accountsApi.profile()).rejects.toMatchObject({ httpStatus: 401 });
    } finally {
      vi.useRealTimers();
    }
  });
});
