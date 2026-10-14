import { ApiError } from "./client";
import type { Me, QuestionnaireDefinition, QuestionnaireSubmission, SigninInput, SignupInput, Tolerance, UserProfile } from "./accounts";

type MockUser = { readonly email: string; readonly password: string; readonly profile: UserProfile; readonly data_source: Me["data_source"] };

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
let currentUser: string | null = null;
let sequence = 0;
let snapshotSequence = 0;
const paramsVersion = "mock-pq-0.1";

function envelope<T>(data: T) {
  return { status: "OK", data, facts: [], warnings: [], params_version: paramsVersion, snapshot_id: `mock:accounts:${++snapshotSequence}`, as_of: new Date().toISOString() };
}

function invalid(field: string, message: string, httpStatus = 422): never {
  throw new ApiError(httpStatus, { status: "INVALID_INPUT", params_version: paramsVersion, field, message, facts: [], warnings: [] });
}

function requireUser(): MockUser {
  const user = currentUser ? users.get(currentUser) : undefined;
  if (!user) throw new ApiError(401, { status: "UNAUTHENTICATED" });
  return user;
}

function me(): Me {
  const user = requireUser();
  return { user_id: user.profile.user_id, data_source: user.data_source };
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
    const email = input.email.trim().toLowerCase();
    if (!email.endsWith(".invalid") || !email.includes("@")) invalid("email", "Use a synthetic .invalid email in the local mock.");
    if (input.password.length < 10 || input.password.length > 128) invalid("password", "Password must have 10 to 128 characters.");
    if (!/^[\p{L} .'-]{1,40}$/u.test(input.display_name)) invalid("display_name", "Name must use 1 to 40 letters, spaces, periods, apostrophes or hyphens.");
    if (users.has(email)) invalid("email", "Account already exists.", 409);
    const user_id = `usr_mock_${++sequence}`;
    users.set(email, {
      email, password: input.password, data_source: "empty",
      profile: { user_id, display_name: { untrusted_text: input.display_name }, language: "en", declared_tolerance: null, questionnaire_version: null, questionnaire: [] },
    });
    currentUser = email;
    return { user_id };
  }
  if (path === "/v1/auth/signin" && options.method === "POST") {
    const input = options.body as SigninInput;
    const email = input.email.trim().toLowerCase();
    const user = users.get(email);
    if (!user || user.password !== input.password) throw new ApiError(401, { status: "UNAUTHENTICATED", message: "Invalid credentials." });
    currentUser = email;
    return { user_id: user.profile.user_id };
  }
  if (path === "/v1/auth/demo-session" && options.method === "POST") {
    const input = options.body as { readonly persona: "camila" | "diego" };
    if (input.persona !== "camila" && input.persona !== "diego") invalid("persona", "Unknown demo persona.");
    const email = `${input.persona}@demo.invalid`;
    users.set(email, {
      email, password: "", data_source: "sample",
      profile: {
        user_id: input.persona, display_name: { untrusted_text: input.persona === "camila" ? "Camila" : "Diego" },
        language: "en", declared_tolerance: input.persona === "camila" ? "aggressive" : "moderate", questionnaire_version: null, questionnaire: [],
      },
    });
    currentUser = email;
    return { user_id: input.persona };
  }
  if (path === "/v1/auth/signout" && options.method === "POST") {
    requireUser();
    currentUser = null;
    return null;
  }
  if (path === "/v1/me") return me();
  const user = requireUser();
  if (path === "/v1/profile" && options.method === "GET") return envelope(user.profile);
  if (path === "/v1/profile/questionnaire" && options.method === "GET") return envelope(definition);
  if (path === "/v1/profile/questionnaire" && options.method === "POST") {
    if (user.profile.user_id === "camila" || user.profile.user_id === "diego") throw new ApiError(403, { status: "PROFILE_READ_ONLY" });
    const input = options.body as QuestionnaireSubmission;
    const answers = new Map(input.answers.map((answer) => [answer.question_id, answer.option_id]));
    if (input.version !== definition.version || input.answers.length !== questions.length || answers.size !== questions.length ||
        definition.questions.some((question) => !question.options.some((option) => option.option_id === answers.get(question.question_id)))) {
      invalid("answers", "Complete every question using this questionnaire version.");
    }
    const total = definition.questions.reduce((score, question) => score + (question.options.find((option) => option.option_id === answers.get(question.question_id))?.score ?? 0), 0);
    const declared_tolerance: Tolerance = total <= 3 ? "conservative" : total <= 7 || answers.get("tight_month") === "pause" ? "moderate" : "aggressive";
    const profile = { ...user.profile, declared_tolerance, questionnaire_version: definition.version, questionnaire: input.answers };
    users.set(user.email, { ...user, profile });
    return envelope(profile);
  }
  if (path === "/v1/profile" && options.method === "PUT") {
    if (user.profile.user_id === "camila" || user.profile.user_id === "diego") throw new ApiError(403, { status: "PROFILE_READ_ONLY" });
    const input = options.body as { readonly display_name: string; readonly language: string };
    if (!/^[\p{L} .'-]{1,40}$/u.test(input.display_name)) invalid("display_name", "Name must use 1 to 40 letters, spaces, periods, apostrophes or hyphens.");
    const profile = { ...user.profile, display_name: { untrusted_text: input.display_name }, language: input.language };
    users.set(user.email, { ...user, profile });
    return envelope(profile);
  }
  if (path === "/v1/profile/sample-data" && options.method === "POST") {
    if (user.profile.user_id === "camila" || user.profile.user_id === "diego") throw new ApiError(403, { status: "PROFILE_READ_ONLY" });
    users.set(user.email, { ...user, data_source: "sample" });
    return me();
  }
  if (path === "/v1/permitted-profile" && options.method === "POST" && user.data_source === "sample") {
    const input = options.body as { readonly tolerance: Tolerance };
    const capacity: Tolerance = "conservative";
    const permitted: Tolerance = capacity;
    return envelope({ permitted, tolerance: input.tolerance, capacity, hard_rules_triggered: [] });
  }
  throw new ApiError(409, { status: "INSUFFICIENT_DATA", params_version: paramsVersion, missing: ["financial data"], facts: [], warnings: [] });
}
