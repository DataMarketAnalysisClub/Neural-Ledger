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
import type { Statements } from "@/contracts/outputs/statements";
import type { Statement } from "@/contracts/outputs/statement";
import type { StatementImport } from "@/contracts/outputs/statement_import";
import type { DocumentIngest } from "@/contracts/outputs/document_ingest";
import type { SpendingStatus } from "@/contracts/outputs/spending_status";
import type { Receipts } from "@/contracts/outputs/receipts";
import type { ReceiptCorrection } from "@/contracts/receipts/receipt_correction";
import type { ExpenseConfirmation } from "@/contracts/expenses/expense_confirmation";
import type { ExpenseProposal } from "@/contracts/outputs/expense_proposal";
import type { Transactions } from "@/contracts/outputs/transactions";
import type { CategoryUpdate } from "@/contracts/transactions/category_update";
import type { InvestmentOverview } from "@/contracts/outputs/investments";
import type { InvestmentLinkOutcome } from "@/contracts/investments/link_outcome";
import type { InvestmentLinkRequest } from "@/contracts/investments/link_request";
import type { InvestmentDocumentsRemoved } from "@/contracts/investments/documents_removed";
import type { Connections } from "@/contracts/connections/connections";
import type { Connection } from "@/contracts/connections/connection";
import type { ConnectionCreate } from "@/contracts/connections/connection_create";
import type { ConnectionToolsUpdate } from "@/contracts/connections/tools_update";
import type { ConnectionSync } from "@/contracts/connections/sync_result";
import type { ConnectedData } from "@/contracts/outputs/connected_data";
import type { BankStart } from "@/contracts/connections/bank_start";
import type { MemoryView } from "@/contracts/memory/memory_view";
import type { MemoryConsent } from "@/contracts/memory/memory_consent";
import type { MemoryConsentUpdate } from "@/contracts/memory/memory_consent_update";
import type { MemoryExport } from "@/contracts/memory/memory_export";
import type { MemoryDeletion } from "@/contracts/memory/memory_deletion";
import type { IncomeDeclaration } from "@/contracts/memory/income_declaration";
import type { IncomeProposal } from "@/contracts/memory/income_proposal";
import { mergeCounters, type MemoryCounters } from "@/features/memory/counters";
import { ApiError, request, requestEnvelope, type ActionOutcome, type ApiIdentity, type AuditEvent, type ChatReply, type Envelope, type PersonaId } from "./client";
import { useOptionalAuth } from "@/features/auth/AuthProvider";
import type { ProfileTolerance } from "./profile";

export type { FinancialState, Forecast, SurplusResult, Commitments, CapacityAssessment, SavingsPlan, PermittedProfile, PurchaseSimulation };
export type { Statements, Statement, StatementImport, Transactions, CategoryUpdate, DocumentIngest, SpendingStatus, Receipts };
export type { InvestmentOverview, InvestmentLinkOutcome, InvestmentLinkRequest };
export type { MemoryView, MemoryConsent, MemoryExport, MemoryDeletion, IncomeDeclaration, IncomeProposal, MemoryCounters };
export type Scenario = "typical" | "conservative" | "stress";
export type IncludePlan = "none" | "recommended" | "active";

// ---- Persona and session --------------------------------------------------------------------

interface PersonaContextValue {
  persona: PersonaId;
  setPersona: (p: PersonaId) => void;
  sessionId: string;
  identity: ApiIdentity;
  /** Starts a new copilot conversation: a new session_id for chat, pending actions and the audit filter. */
  newSession: () => void;
}
const PersonaContext = createContext<PersonaContextValue | null>(null);

/** The persona's (or account's) session for this tab, or a new one when `fresh`. */
function sessionFor(persona: string, fresh = false): string {
  const key = `nl.session.${persona}`;
  const created = `ui-${persona}-${Math.random().toString(36).slice(2, 8)}`;
  try {
    const existing = fresh ? null : sessionStorage.getItem(key);
    if (existing) return existing;
    sessionStorage.setItem(key, created);
    return created;
  } catch {
    return fresh ? created : `ui-${persona}`;
  }
}

export function PersonaProvider({ children, initial = "camila" }: { children: ReactNode; initial?: PersonaId }) {
  const client = useQueryClient();
  const auth = useOptionalAuth();
  const accountId = auth?.mode === "accounts" ? auth.me?.user_id : undefined;
  const [persona, setPersonaState] = useState<PersonaId>(initial);
  const [sessionId, setSessionId] = useState(() => sessionFor(accountId ?? initial));
  const setPersona = useCallback(
    (p: PersonaId) => {
      setPersonaState(p);
      setSessionId(sessionFor(p));
      client.removeQueries(); // nothing from one persona may leak into the other's screens
    },
    [client],
  );
  const newSession = useCallback(() => setSessionId(sessionFor(accountId ?? persona, true)), [accountId, persona]);
  const value = useMemo(() => ({
    persona, setPersona, sessionId, newSession,
    identity: accountId ? { kind: "accounts" as const, user_id: accountId } : { kind: "demo" as const, user_id: persona },
  }), [persona, setPersona, sessionId, newSession, accountId]);
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
  auth?: "demo" | "accounts";
  mode: "offline" | "live";
  language_model: string;
  decision_chain: string[];
  params_version: string;
  audit_chain_ok: boolean;
  tools: string[];
  server_time?: string | null;
  /** Who reads a linked investment account: "fixture" (a synthetic sandbox account) or "fintual" (ADR-044). */
  investments?: string;
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => request<Health>("/health"), staleTime: 30_000 });
}

export function useFinancialState() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "state"], queryFn: () => requestEnvelope<FinancialState>("/v1/state", { identity }) });
}

export function useForecast(scenario: Scenario, includePlan: IncludePlan = "none", horizon = 6) {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "forecast", scenario, includePlan, horizon],
    queryFn: () =>
      requestEnvelope<Forecast>("/v1/forecast", { identity, query: { scenario, include_plan: includePlan, horizon_months: horizon } }),
  });
}

export function useProtectedSurplus(includePlan: IncludePlan = "none") {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "surplus", includePlan],
    queryFn: () => requestEnvelope<SurplusResult>("/v1/protected-surplus", { identity, query: { include_plan: includePlan } }),
  });
}

export function useCommitments() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "commitments"], queryFn: () => requestEnvelope<Commitments>("/v1/commitments", { identity }) });
}

export function useCapacity() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "capacity"], queryFn: () => requestEnvelope<CapacityAssessment>("/v1/capacity", { identity }) });
}

export function useUserProfile() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "profile"], queryFn: () => requestEnvelope<ProfileTolerance>("/v1/profile", { identity }) });
}

export function useSavingsPlan(permittedProfile?: string) {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "plan", permittedProfile ?? "auto"],
    queryFn: () =>
      requestEnvelope<SavingsPlan>("/v1/savings-plan", {
        identity,
        method: "POST",
        body: permittedProfile ? { permitted_profile: permittedProfile } : {},
      }),
  });
}

export function usePermittedProfile(tolerance: string) {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "permitted", tolerance],
    queryFn: () => requestEnvelope<PermittedProfile>("/v1/permitted-profile", { identity, method: "POST", body: { tolerance } }),
  });
}

export interface PendingActions {
  proposals: NonNullable<ActionOutcome["proposal"]>[];
  authorizations: NonNullable<ActionOutcome["authorization"]>[];
}

export function usePending() {
  const { identity, sessionId } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "pending", sessionId],
    queryFn: () => request<PendingActions>("/v1/actions/pending", { identity, query: { session_id: sessionId } }),
  });
}

export interface AuditPage {
  events: AuditEvent[];
  chain_ok: boolean;
}

export function useAudit(sessionId?: string) {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "audit", sessionId ?? "all"],
    queryFn: () => request<AuditPage>("/v1/audit", { identity, query: { session_id: sessionId, limit: 500 } }),
    // Switching the conversation filter keeps the table on screen while it loads; never across identities.
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[0] === identity.user_id ? previous : undefined),
  });
}

/** The spending check-in for the pay cycle of today (ADR-039): the same figures the copilot's get_spending_status reads. */
export function useSpending() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "spending"], queryFn: () => requestEnvelope<SpendingStatus>("/v1/spending", { identity }) });
}

export function useReceipts() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "receipts"], queryFn: () => requestEnvelope<Receipts>("/v1/receipts", { identity }) });
}

export function useStatements() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "statements"], queryFn: () => requestEnvelope<Statements>("/v1/statements", { identity }) });
}

export function useStatement(statementId: string | null) {
  const { identity } = usePersona();
  return useQuery({
    queryKey: [identity.user_id, "statements", statementId],
    queryFn: () => requestEnvelope<Statement>(`/v1/statements/${encodeURIComponent(statementId!)}`, { identity }),
    enabled: statementId !== null,
  });
}

export function useTransactions() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "transactions"], queryFn: () => requestEnvelope<Transactions>("/v1/transactions", { identity }) });
}

/** The linked investment account (ADR-044). No link is a state the screen shows, not an error: 404 NOT_LINKED. */
async function investmentLink(identity: ApiIdentity): Promise<InvestmentLinkOutcome> {
  try {
    return await request<InvestmentLinkOutcome>("/v1/investments/link", { identity });
  } catch (error) {
    const body = error instanceof ApiError ? (error.body as Partial<InvestmentLinkOutcome> | null) : null;
    if (error instanceof ApiError && error.httpStatus === 404 && body?.status === "NOT_LINKED") return body as InvestmentLinkOutcome;
    throw error;
  }
}

/** Only asked by an account that may link one: a demo persona or demo mode never can (S31). */
export function useInvestmentLink(enabled: boolean) {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "investment-link"], queryFn: () => investmentLink(identity), enabled });
}

/** What the copilot knows of the user's investments: the imported documents, else a linked account. Nothing yet is a
 * state the screen shows, not an error: the API answers INSUFFICIENT_DATA with missing ["investment_account"]. */
async function investments(identity: ApiIdentity): Promise<Envelope<InvestmentOverview> | null> {
  try {
    return await requestEnvelope<InvestmentOverview>("/v1/investments", { identity });
  } catch (error) {
    if (error instanceof ApiError && error.detail.missing?.includes("investment_account")) return null;
    throw error;
  }
}

/** Read without calling any provider: importing and syncing are the user's actions. */
export function useInvestments(enabled: boolean) {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "investments"], queryFn: () => investments(identity), enabled });
}

/** The account forgets every investment document it imported (ADR-044). A linked account, if any, stays. */
export function useRemoveInvestmentDocuments() {
  const { identity } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<InvestmentDocumentsRemoved>("/v1/investments/documents", { identity, method: "DELETE" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "investments"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
    },
  });
}

function useInvestmentWrite<T>(send: (identity: ApiIdentity, input: T) => Promise<InvestmentLinkOutcome>) {
  const { identity } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: T) => send(identity, input),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "investment-link"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "investments"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
    },
  });
}

/** Sends the Fintual email and password once; the API keeps only the token it gets back, sealed. Never stored here. */
export function useLinkInvestments() {
  return useInvestmentWrite((identity, body: InvestmentLinkRequest) =>
    request<InvestmentLinkOutcome>("/v1/investments/link", { identity, method: "POST", body }));
}

export function useSyncInvestments() {
  return useInvestmentWrite<void>((identity) => request<InvestmentLinkOutcome>("/v1/investments/sync", { identity, method: "POST" }));
}

export function useUnlinkInvestments() {
  return useInvestmentWrite<void>((identity) => request<InvestmentLinkOutcome>("/v1/investments/link", { identity, method: "DELETE" }));
}

export interface ChainCheck {
  ok: boolean;
  checked: number;
  broken_at: number | null;
  reason: string | null;
}

export function useVerifyChain() {
  const { identity } = usePersona();
  return useMutation({ mutationFn: () => request<ChainCheck>("/v1/audit/verify", { identity }) });
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
  const { identity } = usePersona();
  return useMutation({
    mutationFn: (input: PurchaseInput) =>
      requestEnvelope<PurchaseSimulation>("/v1/simulate-purchase", { identity, method: "POST", body: input }),
  });
}

/**
 * Imports a statement file. Imports feed the transaction ledger only (ADR-029): demo projections still use the demo
 * scenario, and an account without financial data gets no projection from them.
 */
export function useImportStatement() {
  const { identity } = usePersona();
  const client = useQueryClient();
  const auth = useOptionalAuth();
  return useMutation({
    mutationFn: (file: Blob) => requestEnvelope<StatementImport>("/v1/statements", { identity, method: "POST", body: file }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "statements"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "transactions"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
      void auth?.refreshMe(); // an import can turn an empty account into one with statements (ADR-029)
    },
  });
}

/**
 * A file dropped on the copilot (ADR-039): the server decides whether it is a statement or a receipt, reads it,
 * records it once and answers with every workflow step and the spending check-in.
 */
export function useIngestDocument() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  const auth = useOptionalAuth();
  return useMutation({
    /** `kind` is the user's own answer when the file was not recognized, or where they dropped it ("investment" on the Investments page). */
    mutationFn: ({ file, kind }: { file: Blob; kind?: "receipt" | "statement" | "investment" }) =>
      requestEnvelope<DocumentIngest>("/v1/documents", { identity, method: "POST", body: file, query: { session_id: sessionId, kind } }),
    onSettled: () => {
      for (const key of ["statements", "transactions", "audit", "spending", "receipts", "investments"]) void client.invalidateQueries({ queryKey: [identity.user_id, key] });
      void auth?.refreshMe();
    },
  });
}

export type ReceiptView = Receipts[number];
export type { ExpenseProposal };

/**
 * The user confirms an expense the copilot prepared from what they said (ADR-039), completing what it could not
 * tell (cash or card, the category). The amount is the proposal's: this sends no amount. Nothing is stored before.
 */
export function useConfirmExpense() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, ...choice }: { proposalId: string } & Omit<ExpenseConfirmation, "session_id">) =>
      requestEnvelope<ReceiptView>(`/v1/expenses/${encodeURIComponent(proposalId)}/confirm`, {
        identity,
        method: "POST",
        body: { ...choice, session_id: sessionId } satisfies ExpenseConfirmation,
      }),
    onSettled: () => {
      for (const key of ["audit", "spending", "receipts"]) void client.invalidateQueries({ queryKey: [identity.user_id, key] });
    },
  });
}

/**
 * The user's correction of a receipt's total or date (ADR-039). Not optimistic: the receipt, the spending figure and
 * the receipts list are re-read when the API answers. Only this form corrects a receipt; the copilot only asks.
 */
export function useCorrectReceipt() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ receiptId, ...fix }: { receiptId: string } & Omit<ReceiptCorrection, "session_id">) =>
      requestEnvelope<ReceiptView>(`/v1/receipts/${encodeURIComponent(receiptId)}`, {
        identity,
        method: "PATCH",
        body: { ...fix, session_id: sessionId } satisfies ReceiptCorrection,
      }),
    onSettled: () => {
      for (const key of ["audit", "spending", "receipts"]) void client.invalidateQueries({ queryKey: [identity.user_id, key] });
    },
  });
}

export type Transaction = Transactions["transactions"][number];

/**
 * The user sets one transaction's category (ADR-023). Not optimistic: the ledger and its totals are re-read when
 * the API answers. A category the transaction's kind cannot take is an ApiError whose detail lists the allowed ones.
 */
export function useSetCategory() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ txnId, category }: { txnId: string; category: CategoryUpdate["category"] }) =>
      requestEnvelope<Transaction>(`/v1/transactions/${encodeURIComponent(txnId)}`, {
        identity,
        method: "PATCH",
        body: { category, session_id: sessionId } satisfies CategoryUpdate,
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "transactions"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
    },
  });
}

export function useChat() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  const note = useNoteMemoryCounters();
  return useMutation({
    mutationFn: (message: string) => request<ChatReply>("/v1/chat", { identity, method: "POST", body: { session_id: sessionId, message } }),
    onSuccess: (reply) => {
      // The server read these counters; and memory may have moved since in another tab, so ask for the latest.
      note(reply.memory_dependency);
      if (reply.memory_dependency) void client.invalidateQueries({ queryKey: [identity.user_id, "memory-consent"] });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "pending"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
    },
  });
}

/** The ONLY way to authorize: the user confirms the exact terms the card shows, unchanged. */
export function useConfirmProposal() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, terms }: { proposalId: string; terms: unknown }) =>
      request<ActionOutcome>(`/v1/actions/proposals/${encodeURIComponent(proposalId)}/confirm`, {
        identity,
        method: "POST",
        body: { session_id: sessionId, terms },
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "pending"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
    },
  });
}

/** Execution reads its terms from the stored authorization; the UI sends only the id. */
export function useExecute() {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (authorizationId: string) =>
      request<ActionOutcome>("/v1/actions/execute", { identity, method: "POST", body: { session_id: sessionId, authorization_id: authorizationId } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "pending"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "audit"] });
      void client.invalidateQueries({ queryKey: [identity.user_id, "state"] }); // the rule counter is re-read, never incremented locally
    },
  });
}

// ---- Read-only connections (ADR-047) --------------------------------------------------------

export type { Connections, Connection, ConnectionSync, ConnectedData, BankStart };
export type ConnectionTool = Connection["tools"][number];

export function useConnections() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "connections"], queryFn: () => requestEnvelope<Connections>("/v1/connections", { identity }) });
}

/** What the copilot reads: the last sync's answers. Missing data (nothing connected) is an ApiError (409). */
export function useConnectedData() {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "connections", "data"], queryFn: () => requestEnvelope<ConnectedData>("/v1/connections/data", { identity }) });
}

function useConnectionMutation<A, T>(call: (args: A, identity: ApiIdentity, sessionId: string) => Promise<Envelope<T>>, extra: string[] = []) {
  const { identity, sessionId } = usePersona();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: A) => call(args, identity, sessionId),
    onSettled: () => {
      for (const key of ["connections", "audit", ...extra]) void client.invalidateQueries({ queryKey: [identity.user_id, key] });
    },
  });
}

export function useAddConnection() {
  return useConnectionMutation((body: Omit<ConnectionCreate, "consent">, identity, sessionId) =>
    requestEnvelope<Connection>("/v1/connections", { identity, method: "POST", body: { ...body, consent: true, session_id: sessionId } }),
  );
}

export function useSetConnectionTools() {
  return useConnectionMutation(({ id, enabled }: { id: string; enabled: string[] }, identity, sessionId) =>
    requestEnvelope<Connection>(`/v1/connections/${encodeURIComponent(id)}/tools`, { identity, method: "PUT", body: { enabled, session_id: sessionId } satisfies ConnectionToolsUpdate & { session_id: string } }),
  );
}

/** A bank sync imports statements, so the ledger screens are re-read too. */
export function useSyncConnection() {
  return useConnectionMutation((id: string, identity, sessionId) =>
    requestEnvelope<ConnectionSync>(`/v1/connections/${encodeURIComponent(id)}/sync`, { identity, method: "POST", query: { session_id: sessionId } }),
  ["statements", "transactions"]);
}

export function useRemoveConnection() {
  return useConnectionMutation((id: string, identity, sessionId) =>
    requestEnvelope<Connection>(`/v1/connections/${encodeURIComponent(id)}`, { identity, method: "DELETE", query: { session_id: sessionId } }),
  );
}

export function useBankStart() {
  const { identity } = usePersona();
  return useMutation({ mutationFn: () => requestEnvelope<BankStart>("/v1/connections/bank/start", { identity, method: "POST" }) });
}

export function useConnectBank() {
  return useConnectionMutation((exchangeToken: string, identity, sessionId) =>
    requestEnvelope<Connection>("/v1/connections/bank", { identity, method: "POST", body: { exchange_token: exchangeToken, consent: true, session_id: sessionId } }),
  );
}

// ---- User memory (ADR-048): saved only; the user's own HTTP flows, nothing optimistic ---------------------------

const countersKey = (userId: string) => [userId, "memory-counters"] as const;

/**
 * The largest memory counters this tab has seen for the identity (features/memory/counters.ts): from every consent
 * response and every chat reply. They only grow, so a late or out-of-order response never makes an obsolete reply
 * visible again. Null until one is seen.
 */
export function useMemoryCounters(): MemoryCounters | null {
  const { identity } = usePersona();
  const client = useQueryClient();
  const key = countersKey(identity.user_id);
  // Never fetched: written by useNoteMemoryCounters, read here; a refetch keeps what is cached.
  const { data } = useQuery({ queryKey: key, queryFn: () => client.getQueryData<MemoryCounters | null>(key) ?? null, enabled: false, staleTime: Infinity });
  return data ?? null;
}

export function useNoteMemoryCounters() {
  const { identity } = usePersona();
  const client = useQueryClient();
  return useCallback(
    (seen: MemoryCounters | null | undefined) => {
      if (seen) client.setQueryData<MemoryCounters | null>(countersKey(identity.user_id), (known) => mergeCounters(known, seen));
    },
    [client, identity.user_id],
  );
}

/** Every memory query of this identity: a write re-reads them all, so no card or list keeps an old revision. */
function useMemoryRefresh() {
  const { identity } = usePersona();
  const client = useQueryClient();
  return () => {
    for (const key of ["memory", "memory-consent", "audit"]) void client.invalidateQueries({ queryKey: [identity.user_id, key] });
  };
}

/** The consent and the counters that tell a reply or a card it is obsolete (memory_consent). */
export function useMemoryConsent(enabled = true) {
  const { identity } = usePersona();
  const note = useNoteMemoryCounters();
  return useQuery({
    queryKey: [identity.user_id, "memory-consent"],
    queryFn: async () => {
      const consent = await request<MemoryConsent>("/v1/memory/consent", { identity });
      note(consent);
      return consent;
    },
    enabled,
  });
}

export function useSetMemoryConsent() {
  const { identity } = usePersona();
  const refresh = useMemoryRefresh();
  const note = useNoteMemoryCounters();
  return useMutation({
    mutationFn: (consent: MemoryConsentUpdate["consent"]) =>
      request<MemoryConsent>("/v1/memory/consent", { identity, method: "PUT", body: { consent } satisfies MemoryConsentUpdate }),
    onSuccess: note,
    onSettled: refresh,
  });
}

/** What Neural Ledger keeps about the user. Available without consent; the check is then null. */
export function useMemory(enabled = true) {
  const { identity } = usePersona();
  return useQuery({ queryKey: [identity.user_id, "memory"], queryFn: () => request<MemoryView>("/v1/memory", { identity }), enabled });
}

/** The card's confirmation: the amount the user selected or typed, with the proposal's origin (the server's). */
export function useConfirmMemory() {
  const { identity, sessionId } = usePersona();
  const refresh = useMemoryRefresh();
  return useMutation({
    mutationFn: ({ proposalId, ...declaration }: { proposalId: string } & Omit<IncomeDeclaration, "session_id">) =>
      request<MemoryView>(`/v1/memory/proposals/${encodeURIComponent(proposalId)}/confirm`, {
        identity,
        method: "POST",
        body: { ...declaration, session_id: sessionId } satisfies IncomeDeclaration,
      }),
    onSettled: refresh,
  });
}

/** Perfil's declaration: a new version of the chain (expected_version), or its first one. */
export function useDeclareIncome() {
  const { identity } = usePersona();
  const refresh = useMemoryRefresh();
  return useMutation({
    mutationFn: (declaration: IncomeDeclaration) => request<MemoryView>("/v1/profile/income", { identity, method: "PUT", body: declaration }),
    onSettled: refresh,
  });
}

export function useDeleteMemoryChain() {
  const { identity } = usePersona();
  const refresh = useMemoryRefresh();
  return useMutation({
    mutationFn: (chainId: string) => request<MemoryDeletion>(`/v1/memory/${encodeURIComponent(chainId)}`, { identity, method: "DELETE" }),
    onSettled: refresh,
  });
}

/** Every declaration version, for the user to download (G02). Read on demand, never cached. */
export function useMemoryExport() {
  const { identity } = usePersona();
  return useMutation({ mutationFn: () => request<MemoryExport>("/v1/memory/export", { identity }) });
}
