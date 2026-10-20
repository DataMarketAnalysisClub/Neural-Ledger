import { ApiError } from "./client";
import type { AccountDeletion, AccountDeletionInput, AuthError, DataExport, AuthSession, Me, ProfileUpdate, QuestionnaireDefinition, QuestionnaireSubmission, SigninInput, SignupInput, Tolerance, UserProfile } from "./accounts";

type MockUser = { readonly email: string; readonly password: string; readonly profile: UserProfile; readonly data_source: Me["data_source"] };
type MockSession = { readonly email: string; readonly expires_at: string };

const questions = [
  { question_id: "set_aside", options: ["small_part", "about_half", "most"] },
  { question_id: "tight_month", options: ["pause", "keep_cut_elsewhere", "keep_as_intended"] },
  { question_id: "goal_vs_room", options: ["spending_room", "balance", "goal_on_time"] },
  { question_id: "surprise", options: ["very_stressed", "uneasy_but_ok", "calm"] },
  { question_id: "habit", options: ["never_or_stopped", "sometimes", "regularly"] },
] as const;
const definition: QuestionnaireDefinition = {
  version: "pq-0.1",
  questions: questions.map(({ question_id, options }) => ({
    question_id, copy_key: `questionnaire.${question_id}.prompt`,
    options: options.map((option_id, score) => ({ option_id, score, copy_key: `questionnaire.${question_id}.options.${option_id}` })),
  })),
};
const users = new Map<string, MockUser>();
let currentSession: MockSession | null = null;
let sequence = 0;
let snapshotSequence = 0;
const paramsVersion = "mock-pq-0.1";

function envelope<T>(data: T) {
  return { status: "OK", data, facts: [], warnings: [], params_version: paramsVersion, snapshot_id: `mock:accounts:${++snapshotSequence}`, as_of: new Date().toISOString() };
}

/** An auth-route or request-body rejection: the strict auth error body (auth/error.schema.json). */
function invalid(field: string, message: string): never {
  throw new ApiError(422, { status: "INVALID_INPUT", field, message } satisfies AuthError);
}

/** A value the domain rejects: an INVALID_INPUT envelope (common/envelope.schema.json), as the API answers it. */
function rejected(field: string, message: string): never {
  throw new ApiError(422, { status: "INVALID_INPUT", params_version: paramsVersion, field, allowed: [], message, facts: [], warnings: [] });
}

/** Financial reads that exist on the HTTP API; the mock holds no financial data, so they answer INSUFFICIENT_DATA. */
const FINANCIAL_PATHS: ReadonlySet<string> = new Set([
  "/v1/state", "/v1/commitments", "/v1/forecast", "/v1/simulate-purchase", "/v1/protected-surplus", "/v1/capacity", "/v1/permitted-profile", "/v1/savings-plan",
]);

function requireSession(): { readonly user: MockUser; readonly session: MockSession } {
  const session = currentSession;
  const user = session ? users.get(session.email) : undefined;
  if (!session || !user || Date.now() >= Date.parse(session.expires_at)) {
    currentSession = null;
    throw new ApiError(401, { status: "UNAUTHENTICATED", message: "authentication required" } satisfies AuthError);
  }
  return { user, session };
}

function createSession(user: MockUser): AuthSession {
  const expires_at = new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString();
  currentSession = { email: user.email, expires_at };
  return { user_id: user.profile.user_id, expires_at };
}

function me(): Me {
  const { user, session } = requireSession();
  return { user_id: user.profile.user_id, data_source: user.data_source, expires_at: session.expires_at };
}

export async function mockRequest(
  path: string,
  options: { readonly method: string; readonly body: unknown; readonly query?: Record<string, string | number | undefined | null> },
): Promise<unknown> {
  if (path === "/health") {
    return {
      status: "ok", auth: "accounts", mode: "offline", language_model: "mock", decision_chain: [],
      params_version: paramsVersion, audit_chain_ok: true, tools: [],
    };
  }
  if (path === "/v1/auth/signup" && options.method === "POST") {
    const input = options.body as SignupInput;
    if (input.sandbox_acknowledged !== true) invalid("sandbox_acknowledged", "Acknowledge the sandbox notice.");
    const email = input.email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.invalid$/.test(email)) invalid("email", "Use a synthetic .invalid email in the local mock.");
    if (input.password.length < 10 || input.password.length > 128) invalid("password", "Password must have 10 to 128 characters.");
    if (!/^[\p{L} .'-]{1,40}$/u.test(input.display_name)) invalid("display_name", "Name must use 1 to 40 letters, spaces, periods, apostrophes or hyphens.");
    if (input.language !== undefined && !/^[a-z]{2}$/.test(input.language)) invalid("language", "invalid language");
    if (users.has(email)) throw new ApiError(409, { status: "EMAIL_TAKEN", message: "email already registered", field: "email" } satisfies AuthError);
    const user_id = `usr_mock_${++sequence}`;
    const user: MockUser = {
      email, password: input.password, data_source: "empty",
      profile: { user_id, display_name: { untrusted_text: input.display_name }, language: input.language ?? "en", declared_tolerance: null, questionnaire_version: null, questionnaire: [] },
    };
    users.set(email, user);
    return createSession(user);
  }
  if (path === "/v1/auth/signin" && options.method === "POST") {
    const input = options.body as SigninInput;
    const email = input.email.trim().toLowerCase();
    const user = users.get(email);
    if (!user || user.password !== input.password) throw new ApiError(401, { status: "INVALID_CREDENTIALS", message: "invalid credentials" } satisfies AuthError);
    return createSession(user);
  }
  if (path === "/v1/auth/demo-session" && options.method === "POST") {
    const input = options.body as { readonly persona: "camila" | "diego" };
    if (input.persona !== "camila" && input.persona !== "diego") invalid("persona", "Unknown demo persona.");
    const email = `${input.persona}@demo.invalid`;
    const user: MockUser = {
      email, password: "", data_source: "persona",
      profile: {
        user_id: input.persona, display_name: { untrusted_text: input.persona === "camila" ? "Camila" : "Diego" },
        language: "en", declared_tolerance: input.persona === "camila" ? "aggressive" : "moderate", questionnaire_version: null, questionnaire: [],
      },
    };
    users.set(email, user);
    return createSession(user);
  }
  if (path === "/v1/auth/signout" && options.method === "POST") {
    requireSession();
    currentSession = null;
    return null;
  }
  if (path === "/v1/me") return me();
  const { user } = requireSession();
  if (path === "/v1/profile" && options.method === "GET") return envelope(user.profile);
  if (path === "/v1/profile/questionnaire" && options.method === "GET") return envelope(definition);
  if (path === "/v1/profile/questionnaire" && options.method === "POST") {
    if (user.data_source === "persona") throw new ApiError(403, { status: "PROFILE_READ_ONLY", message: "profile is read only" } satisfies AuthError);
    const input = options.body as QuestionnaireSubmission;
    const answers = new Map(input.answers.map((answer) => [answer.question_id, answer.option_id]));
    if (input.version !== definition.version || input.answers.length !== questions.length || answers.size !== questions.length ||
        definition.questions.some((question) => !question.options.some((option) => option.option_id === answers.get(question.question_id)))) {
      rejected("answers", "Complete every question using this questionnaire version.");
    }
    const total = definition.questions.reduce((score, question) => score + (question.options.find((option) => option.option_id === answers.get(question.question_id))?.score ?? 0), 0);
    const declared_tolerance: Tolerance = total <= 3 ? "conservative" : total <= 7 || answers.get("tight_month") === "pause" ? "moderate" : "aggressive";
    const profile = { ...user.profile, declared_tolerance, questionnaire_version: definition.version, questionnaire: input.answers };
    users.set(user.email, { ...user, profile });
    return envelope(profile);
  }
  if (path === "/v1/profile" && options.method === "PUT") {
    if (user.data_source === "persona") throw new ApiError(403, { status: "PROFILE_READ_ONLY", message: "profile is read only" } satisfies AuthError);
    const input = options.body as ProfileUpdate;
    if (input.display_name === undefined && input.language === undefined) invalid("body", "invalid input");
    if (input.display_name !== undefined && !/^[\p{L} .'-]{1,40}$/u.test(input.display_name)) rejected("display_name", "Name must use 1 to 40 letters, spaces, periods, apostrophes or hyphens.");
    if (input.language !== undefined && !/^[a-z]{2}$/.test(input.language)) rejected("language", "invalid language");
    const profile = { ...user.profile, display_name: input.display_name === undefined ? user.profile.display_name : { untrusted_text: input.display_name }, language: input.language ?? user.profile.language };
    users.set(user.email, { ...user, profile });
    return envelope(profile);
  }
  if (path === "/v1/account" && options.method === "DELETE") {
    const input = options.body as AccountDeletionInput;
    if (user.data_source === "persona") {
      if (input.confirm !== "RESET") invalid("confirm", "type RESET to reset the demo data");
      return { status: "RESET", erased: {}, audit_events_erased: 0 } satisfies AccountDeletion;
    }
    if (input.confirm.trim() !== "DELETE" && input.confirm.trim().toLowerCase() !== user.email) invalid("confirm", "type DELETE or your email to confirm");
    if (input.password !== user.password) throw new ApiError(401, { status: "INVALID_CREDENTIALS", message: "invalid credentials" } satisfies AuthError);
    users.delete(user.email);
    currentSession = null;
    return { status: "DELETED", erased: { user_accounts: 1, user_profiles: 1, sessions: 1 }, audit_events_erased: 0 } satisfies AccountDeletion;
  }
  if (path === "/v1/me/export" && options.method === "GET") {
    const persona = user.data_source === "persona";
    return {
      format: "neural-ledger-export-2", exported_at: new Date().toISOString(), user_id: user.profile.user_id,
      account: persona ? null : { email: user.email, created_at: new Date().toISOString(), sample_data: false },
      profile: { ...user.profile, display_name: user.profile.display_name.untrusted_text },
      statements: [], transactions: [], receipts: [], connections: [], savings_rules: [],
      investments: { link: null, latest_snapshot: null, documents: [] },
      memory: { consent: { consent: "missing", consent_generation: 0, memory_revision: 0 }, declarations: { catalog_version: "mem-0.1", declarations: [] } },
      audit_events: [],
    } satisfies DataExport;
  }
  // Only a read-only demo persona has financial data; a new account stays empty.
  if (path === "/v1/permitted-profile" && options.method === "POST" && user.data_source === "persona") {
    const input = options.body as { readonly tolerance: Tolerance };
    const capacity: Tolerance = "conservative";
    const permitted: Tolerance = capacity;
    return envelope({ permitted, tolerance: input.tolerance, capacity, hard_rules_triggered: [] });
  }
  if (FINANCIAL_PATHS.has(path)) {
    throw new ApiError(409, { status: "INSUFFICIENT_DATA", params_version: paramsVersion, missing: ["financial data"], facts: [], warnings: [] });
  }
  // Anything else is not served by this mock (FastAPI's answer for an unknown route).
  throw new ApiError(404, { detail: "Not Found" });
}
