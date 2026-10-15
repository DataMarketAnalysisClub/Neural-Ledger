import { request, requestEnvelope, type Envelope } from "./client";
import type { PermittedProfile } from "@/contracts/outputs/permitted_profile";

export type Tolerance = "conservative" | "moderate" | "aggressive";

export interface Me {
  readonly user_id: string;
  readonly data_source: "empty" | "sample" | "persona";
  readonly expires_at: string;
}

export interface AuthSession {
  readonly user_id: string;
  readonly expires_at: string;
}

export type AuthError =
  | { readonly status: "INVALID_INPUT"; readonly message: string; readonly field: string }
  | { readonly status: "IDENTITY_HEADER_REJECTED" | "UNAUTHENTICATED" | "INVALID_CREDENTIALS" | "ORIGIN_REJECTED" | "PROFILE_READ_ONLY" | "NOT_FOUND" | "EMAIL_TAKEN"; readonly message: string; readonly field?: string };

export interface UserProfile {
  readonly user_id: string;
  readonly display_name: { readonly untrusted_text: string };
  readonly language: string;
  readonly declared_tolerance: Tolerance | null;
  readonly questionnaire_version: string | null;
  readonly questionnaire: readonly { readonly question_id: string; readonly option_id: string }[];
}

export interface QuestionnaireDefinition {
  readonly version: string;
  readonly questions: readonly {
    readonly question_id: string;
    readonly copy_key: string;
    readonly options: readonly { readonly option_id: string; readonly copy_key: string; readonly score: number }[];
  }[];
}

export interface QuestionnaireSubmission {
  readonly version: string;
  readonly answers: readonly { readonly question_id: string; readonly option_id: string }[];
}

export interface SignupInput {
  readonly email: string;
  readonly password: string;
  readonly display_name: string;
  readonly language?: string;
}

export interface SigninInput {
  readonly email: string;
  readonly password: string;
}

export type ProfileUpdate =
  | { readonly display_name: string; readonly language?: string }
  | { readonly display_name?: string; readonly language: string };

export const accountsApi = {
  me: () => request<Me>("/v1/me"),
  signup: (input: SignupInput) => request<AuthSession>("/v1/auth/signup", { method: "POST", body: input }),
  signin: (input: SigninInput) => request<AuthSession>("/v1/auth/signin", { method: "POST", body: input }),
  demoSession: (persona: "camila" | "diego") => request<AuthSession>("/v1/auth/demo-session", { method: "POST", body: { persona } }),
  signout: () => request<null>("/v1/auth/signout", { method: "POST" }),
  profile: () => requestEnvelope<UserProfile>("/v1/profile", {}),
  permitted: (tolerance: Tolerance) => requestEnvelope<PermittedProfile>("/v1/permitted-profile", { method: "POST", body: { tolerance } }),
  questionnaire: () => requestEnvelope<QuestionnaireDefinition>("/v1/profile/questionnaire", {}),
  submitQuestionnaire: (input: QuestionnaireSubmission) => request<unknown>("/v1/profile/questionnaire", { method: "POST", body: input }),
  updateProfile: (input: ProfileUpdate) =>
    request<unknown>("/v1/profile", { method: "PUT", body: input }),
  useSampleData: () => request<unknown>("/v1/profile/sample-data", { method: "POST" }),
};

export type ProfileEnvelope = Envelope<UserProfile>;
