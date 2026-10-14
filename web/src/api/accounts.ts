import { request, requestEnvelope, type Envelope } from "./client";
import type { PermittedProfile } from "@/contracts/outputs/permitted_profile";

export type Tolerance = "conservative" | "moderate" | "aggressive";

export interface Me {
  readonly user_id: string;
  readonly data_source: "empty" | "sample";
}

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
}

export interface SigninInput {
  readonly email: string;
  readonly password: string;
}

export const accountsApi = {
  me: () => request<Me>("/v1/me"),
  signup: (input: SignupInput) => request<unknown>("/v1/auth/signup", { method: "POST", body: input }),
  signin: (input: SigninInput) => request<unknown>("/v1/auth/signin", { method: "POST", body: input }),
  demoSession: (persona: "camila" | "diego") => request<unknown>("/v1/auth/demo-session", { method: "POST", body: { persona } }),
  signout: () => request<unknown>("/v1/auth/signout", { method: "POST" }),
  profile: () => requestEnvelope<UserProfile>("/v1/profile", {}),
  permitted: (tolerance: Tolerance) => requestEnvelope<PermittedProfile>("/v1/permitted-profile", { method: "POST", body: { tolerance } }),
  questionnaire: () => requestEnvelope<QuestionnaireDefinition>("/v1/profile/questionnaire", {}),
  submitQuestionnaire: (input: QuestionnaireSubmission) => request<unknown>("/v1/profile/questionnaire", { method: "POST", body: input }),
  updateProfile: (input: { readonly display_name: string; readonly language: string }) =>
    request<unknown>("/v1/profile", { method: "PUT", body: input }),
  useSampleData: () => request<unknown>("/v1/profile/sample-data", { method: "POST" }),
};

export type ProfileEnvelope = Envelope<UserProfile>;
