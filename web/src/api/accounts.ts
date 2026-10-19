import { request, requestEnvelope, type Envelope } from "./client";
import type { AuthenticatedUser } from "@/contracts/auth/me";
import type { AuthSession as SessionReceipt } from "@/contracts/auth/session";
import type { AuthError as AuthErrorBody } from "@/contracts/auth/error";
import type { SignupRequest } from "@/contracts/auth/signup_request";
import type { SigninRequest } from "@/contracts/auth/signin_request";
import type { DemoSessionRequest } from "@/contracts/auth/demo_session_request";
import type { AccountDeletionRequest } from "@/contracts/auth/account_deletion_request";
import type { AccountDeletion as AccountDeletionBody } from "@/contracts/auth/account_deletion";
import type { ProfileUpdate as ProfileUpdateBody } from "@/contracts/profile/profile_update";
import type { Questionnaire } from "@/contracts/profile/questionnaire";
import type { PermittedProfile } from "@/contracts/outputs/permitted_profile";
import type { Answer, UserProfile as UserProfileRecord } from "@/contracts/outputs/user_profile";

/* The generated contracts are the source of truth; these names only narrow them where the schema says more than its type. */

export type Tolerance = NonNullable<UserProfileRecord["declared_tolerance"]>;
export type Me = Readonly<AuthenticatedUser>;
export type AuthSession = Readonly<SessionReceipt>;

/** The schema requires `field` when the status is INVALID_INPUT (an if/then the generator does not express). */
export type AuthError =
  | { readonly status: "INVALID_INPUT"; readonly message: string; readonly field: string }
  | { readonly status: Exclude<AuthErrorBody["status"], "INVALID_INPUT">; readonly message: string; readonly field?: string };

export type UserProfile = Readonly<UserProfileRecord>;
export type QuestionnaireDefinition = Readonly<Questionnaire>;

/** The submitted version comes from the questionnaire the server returned; the server checks it and every answer. */
export interface QuestionnaireSubmission {
  readonly version: string;
  readonly answers: Answer[];
}

export type SignupInput = Readonly<SignupRequest>;
export type SigninInput = Readonly<SigninRequest>;
export type DemoPersona = DemoSessionRequest["persona"];
export type AccountDeletionInput = Readonly<AccountDeletionRequest>;
export type AccountDeletion = Readonly<AccountDeletionBody>;

/** At least one field: an empty body is rejected with INVALID_INPUT on `body`. */
export type ProfileUpdate = Readonly<ProfileUpdateBody> & ({ readonly display_name: string } | { readonly language: string });

export const accountsApi = {
  me: () => request<Me>("/v1/me"),
  signup: (input: SignupInput) => request<AuthSession>("/v1/auth/signup", { method: "POST", body: input }),
  signin: (input: SigninInput) => request<AuthSession>("/v1/auth/signin", { method: "POST", body: input }),
  demoSession: (persona: DemoPersona) => request<AuthSession>("/v1/auth/demo-session", { method: "POST", body: { persona } satisfies DemoSessionRequest }),
  signout: () => request<null>("/v1/auth/signout", { method: "POST" }),
  /** G03: an account sends its password and DELETE (or its email); a demo persona sends RESET. */
  deleteAccount: (input: AccountDeletionInput) => request<AccountDeletion>("/v1/account", { method: "DELETE", body: input }),
  profile: () => requestEnvelope<UserProfile>("/v1/profile", {}),
  permitted: (tolerance: Tolerance) => requestEnvelope<PermittedProfile>("/v1/permitted-profile", { method: "POST", body: { tolerance } }),
  questionnaire: () => requestEnvelope<QuestionnaireDefinition>("/v1/profile/questionnaire", {}),
  submitQuestionnaire: (input: QuestionnaireSubmission) => request<unknown>("/v1/profile/questionnaire", { method: "POST", body: input }),
  updateProfile: (input: ProfileUpdate) =>
    request<unknown>("/v1/profile", { method: "PUT", body: input }),
};

export type ProfileEnvelope = Envelope<UserProfile>;
