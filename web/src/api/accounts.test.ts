import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";
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

  it("returns an INVALID_INPUT envelope with a field for a rejected profile edit", async () => {
    await accountsApi.signup({ email: "invalid-name@example.invalid", password: "synthetic-password-five", display_name: "Valid Tester" });

    const update = accountsApi.updateProfile({ display_name: "123", language: "en" });

    await expect(update).rejects.toMatchObject({
      httpStatus: 422,
      body: { status: "INVALID_INPUT", params_version: expect.stringMatching(/^mock-/), field: "display_name", facts: [], warnings: [] },
    });
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

  it("rejects a write to a demo persona profile", async () => {
    await accountsApi.demoSession("diego");

    await expect(accountsApi.updateProfile({ display_name: "Altered", language: "en" })).rejects.toMatchObject({
      httpStatus: 403, body: { status: "PROFILE_READ_ONLY" },
    });
  });
});
