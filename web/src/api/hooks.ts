/**
 * React Query hooks, one per endpoint. Money actions (confirm, execute) are mutations that never
 * update the UI optimistically: the screen changes only when the API answers.
 */
import { createContext, createElement, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FinancialState } from "@/contracts/outputs/financial_state";
import type { Forecast } from "@/contracts/outputs/forecast";
import type { SurplusResult } from "@/contracts/outputs/protected_surplus";
import type { Commitments } from "@/contracts/outputs/commitments";
import type { CapacityAssessment } from "@/contracts/outputs/capacity";
import type { SavingsPlan } from "@/contracts/outputs/savings_plan";
import type { PermittedProfile } from "@/contracts/outputs/permitted_profile";
import type { PurchaseSimulation } from "@/contracts/outputs/purchase_simulation";
import { request, requestEnvelope, type ActionOutcome, type AuditEvent, type ChatReply, type PersonaId } from "./client";
import type { ProfileTolerance } from "./profile";

export type { FinancialState, Forecast, SurplusResult, Commitments, CapacityAssessment, SavingsPlan, PermittedProfile, PurchaseSimulation };
export type Scenario = "typical" | "conservative" | "stress";
export type IncludePlan = "none" | "recommended" | "active";

// ---- Persona and session --------------------------------------------------------------------

interface PersonaContextValue {
  persona: PersonaId;
  setPersona: (p: PersonaId) => void;
  sessionId: string;
}
const PersonaContext = createContext<PersonaContextValue | null>(null);

function sessionFor(persona: PersonaId): string {
  const key = `nl.session.${persona}`;
  try {
    const existing = sessionStorage.getItem(key);
    if (existing) return existing;
    const created = `ui-${persona}-${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem(key, created);
    return created;
  } catch {
    return `ui-${persona}`;
  }
}

export function PersonaProvider({ children, initial = "camila" }: { children: ReactNode; initial?: PersonaId }) {
  const client = useQueryClient();
  const [persona, setPersonaState] = useState<PersonaId>(initial);
  const setPersona = useCallback(
    (p: PersonaId) => {
      setPersonaState(p);
      client.removeQueries(); // nothing from one persona may leak into the other's screens
    },
    [client],
  );
  const value = useMemo(() => ({ persona, setPersona, sessionId: sessionFor(persona) }), [persona, setPersona]);
  return createElement(PersonaContext.Provider, { value }, children);
}

export function usePersona(): PersonaContextValue {
  const value = useContext(PersonaContext);
  if (!value) throw new Error("usePersona outside PersonaProvider");
  return value;
}

// ---- Reads ------------------------------------------------------------------------------------

export interface Health {
  status: string;
  mode: "offline" | "live";
  language_model: string;
  decision_chain: string[];
  params_version: string;
  audit_chain_ok: boolean;
  tools: string[];
  server_time?: string | null;
}

export function useHealth() {
  const { persona } = usePersona();
  return useQuery({ queryKey: ["health"], queryFn: () => request<Health>("/health", { user: persona }), staleTime: 30_000 });
}

export function useFinancialState() {
  const { persona } = usePersona();
  return useQuery({ queryKey: [persona, "state"], queryFn: () => requestEnvelope<FinancialState>("/v1/state", { user: persona }) });
}

export function useForecast(scenario: Scenario, includePlan: IncludePlan = "none", horizon = 6) {
  const { persona } = usePersona();
  return useQuery({
    queryKey: [persona, "forecast", scenario, includePlan, horizon],
    queryFn: () =>
      requestEnvelope<Forecast>("/v1/forecast", { user: persona, query: { scenario, include_plan: includePlan, horizon_months: horizon } }),
  });
}

export function useProtectedSurplus(includePlan: IncludePlan = "none") {
  const { persona } = usePersona();
  return useQuery({
    queryKey: [persona, "surplus", includePlan],
    queryFn: () => requestEnvelope<SurplusResult>("/v1/protected-surplus", { user: persona, query: { include_plan: includePlan } }),
  });
}

export function useCommitments() {
  const { persona } = usePersona();
  return useQuery({ queryKey: [persona, "commitments"], queryFn: () => requestEnvelope<Commitments>("/v1/commitments", { user: persona }) });
}

export function useCapacity() {
  const { persona } = usePersona();
  return useQuery({ queryKey: [persona, "capacity"], queryFn: () => requestEnvelope<CapacityAssessment>("/v1/capacity", { user: persona }) });
}

export function useUserProfile() {
  const { persona } = usePersona();
  return useQuery({ queryKey: [persona, "profile"], queryFn: () => requestEnvelope<ProfileTolerance>("/v1/profile", { user: persona }) });
}

export function useSavingsPlan(permittedProfile?: string) {
  const { persona } = usePersona();
  return useQuery({
    queryKey: [persona, "plan", permittedProfile ?? "auto"],
    queryFn: () =>
      requestEnvelope<SavingsPlan>("/v1/savings-plan", {
        user: persona,
        method: "POST",
        body: permittedProfile ? { permitted_profile: permittedProfile } : {},
      }),
  });
}

export function usePermittedProfile(tolerance: string) {
  const { persona } = usePersona();
  return useQuery({
    queryKey: [persona, "permitted", tolerance],
    queryFn: () => requestEnvelope<PermittedProfile>("/v1/permitted-profile", { user: persona, method: "POST", body: { tolerance } }),
  });
}

export interface PendingActions {
  proposals: NonNullable<ActionOutcome["proposal"]>[];
  authorizations: NonNullable<ActionOutcome["authorization"]>[];
}

export function usePending() {
  const { persona, sessionId } = usePersona();
  return useQuery({
    queryKey: [persona, "pending", sessionId],
    queryFn: () => request<PendingActions>("/v1/actions/pending", { user: persona, query: { session_id: sessionId } }),
  });
}

export interface AuditPage {
  events: AuditEvent[];
  chain_ok: boolean;
}

export function useAudit(sessionId?: string) {
  const { persona } = usePersona();
  return useQuery({
    queryKey: [persona, "audit", sessionId ?? "all"],
    queryFn: () => request<AuditPage>("/v1/audit", { user: persona, query: { session_id: sessionId, limit: 500 } }),
  });
}

export interface ChainCheck {
  ok: boolean;
  checked: number;
  broken_at: number | null;
  reason: string | null;
}

export function useVerifyChain() {
  const { persona } = usePersona();
  return useMutation({ mutationFn: () => request<ChainCheck>("/v1/audit/verify", { user: persona }) });
}

// ---- Writes -----------------------------------------------------------------------------------

export interface PurchaseInput {
  amount: number;
  installments: number;
  first_installment_month?: string;
  monthly_rate?: number;
  include_plan?: IncludePlan;
}

export function useSimulatePurchase() {
  const { persona } = usePersona();
  return useMutation({
    mutationFn: (input: PurchaseInput) =>
      requestEnvelope<PurchaseSimulation>("/v1/simulate-purchase", { user: persona, method: "POST", body: input }),
  });
}

export function useChat() {
  const { persona, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => request<ChatReply>("/v1/chat", { user: persona, method: "POST", body: { session_id: sessionId, message } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [persona, "pending"] });
      void client.invalidateQueries({ queryKey: [persona, "audit"] });
    },
  });
}

/** The ONLY way to authorize: the user confirms the exact terms the card shows, unchanged. */
export function useConfirmProposal() {
  const { persona, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, terms }: { proposalId: string; terms: unknown }) =>
      request<ActionOutcome>(`/v1/actions/proposals/${encodeURIComponent(proposalId)}/confirm`, {
        user: persona,
        method: "POST",
        body: { session_id: sessionId, terms },
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [persona, "pending"] });
      void client.invalidateQueries({ queryKey: [persona, "audit"] });
    },
  });
}

/** Execution reads its terms from the stored authorization; the UI sends only the id. */
export function useExecute() {
  const { persona, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (authorizationId: string) =>
      request<ActionOutcome>("/v1/actions/execute", { user: persona, method: "POST", body: { session_id: sessionId, authorization_id: authorizationId } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [persona, "pending"] });
      void client.invalidateQueries({ queryKey: [persona, "audit"] });
      void client.invalidateQueries({ queryKey: [persona, "state"] }); // the rule counter is re-read, never incremented locally
    },
  });
}
