import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { ArrowUp, ChatText, Info, NotePencil, SealCheck, Wrench } from "@phosphor-icons/react";
import { useChat, useConfirmProposal, useExecute, useFinancialState, usePending, usePersona } from "@/api/hooks";
import { ApiError, type ActionOutcome, type ChatReply } from "@/api/client";
import { ProposalReceipt, VerdictBanner } from "@/components/actions";
import { Button, ErrorState, PageHeader, StatusBadge } from "@/components/ui";
import { t, tList } from "@/i18n";

type Proposal = NonNullable<ActionOutcome["proposal"]>;
type Authorization = NonNullable<ActionOutcome["authorization"]>;

interface Message {
  id: number;
  role: "user" | "copilot";
  text: string;
  reply?: ChatReply;
}

function outcomeFrom(error: unknown): ActionOutcome | null {
  if (error instanceof ApiError && error.body && typeof error.body === "object" && "status" in error.body) return error.body as ActionOutcome;
  return null;
}

/**
 * One conversation per session_id. A new conversation (or another persona) remounts it, so the log, the pending
 * proposal and every request state start empty; the API then answers for the new session only.
 * shortcut: the log lives only in this component, so a reload or a new conversation drops it; replace with
 * GET /v1/chat/history when the backend stores conversations (plan item D2).
 */
export function CopilotPage() {
  const { sessionId } = usePersona();
  return <Conversation key={sessionId} />;
}

function Conversation() {
  const { newSession } = usePersona();
  const location = useLocation();
  const initialPrompt = (location.state as { prompt?: string } | null)?.prompt ?? "";
  const state = useFinancialState();
  const chat = useChat();
  const pending = usePending();
  const confirm = useConfirmProposal();
  const execute = useExecute();
  const currency = state.data?.data?.currency ?? "CLP";

  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState(initialPrompt);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [authorization, setAuthorization] = useState<Authorization | null>(null);
  const [receipt, setReceipt] = useState<ActionOutcome["receipt"]>(null);
  const nextId = useRef(1);
  const logRef = useRef<HTMLOListElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // After a reload nothing is in local state yet: show whatever the API says is pending for this
  // session. The API is the source of truth; local state only takes over once this tab acts.
  const fresh = !proposal && !authorization && !receipt;
  const pendingAuth = fresh ? (pending.data?.authorizations[0] ?? null) : null;
  const pendingProposal = fresh && !pendingAuth ? (pending.data?.proposals[0] ?? null) : null;
  const shownAuthorization = authorization ?? pendingAuth;
  const shownProposal = proposal ?? pendingProposal;

  useEffect(() => {
    logRef.current?.lastElementChild?.scrollIntoView({ block: "end" });
  }, [messages, chat.isPending]);

  function send(text: string) {
    const message = text.trim();
    if (!message || chat.isPending) return;
    setMessages((m) => [...m, { id: nextId.current++, role: "user", text: message }]);
    setDraft("");
    chat.mutate(message, {
      onSuccess: (reply) => {
        setMessages((m) => [...m, { id: nextId.current++, role: "copilot", text: reply.text, reply }]);
        if (reply.pending_proposal) {
          setProposal(reply.pending_proposal as Proposal);
          setAuthorization(null);
          setReceipt(null);
          confirm.reset();
          execute.reset();
        }
      },
      onSettled: () => inputRef.current?.focus(),
    });
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(draft);
  }

  function onConfirm(p: Proposal) {
    // The exact terms received from the API go back unchanged. Nothing on screen changes until it answers.
    confirm.mutate(
      { proposalId: p.proposal_id, terms: p.terms },
      {
        onSuccess: (outcome) => {
          if (outcome.authorization) setAuthorization(outcome.authorization);
        },
      },
    );
  }

  function onExecute(a: Authorization) {
    execute.mutate(a.authorization_id, {
      onSuccess: (outcome) => {
        if (outcome.receipt) setReceipt(outcome.receipt);
        if (outcome.authorization) setAuthorization(outcome.authorization);
      },
    });
  }

  const blocked = useMemo(() => outcomeFrom(confirm.error) ?? outcomeFrom(execute.error), [confirm.error, execute.error]);
  const prompts = tList("copilot.prompts");

  return (
    <>
      <PageHeader
        title={t("copilot.title")}
        subtitle={t("copilot.subtitle")}
        actions={
          <Button variant="secondary" onClick={newSession}>
            <NotePencil aria-hidden className="size-4" />
            {t("copilot.newConversation")}
          </Button>
        }
      />

      <div className="grid gap-10 xl:grid-cols-[1fr_400px]">
        <section aria-label={t("copilot.title")} className="flex h-[calc(100dvh-15rem)] min-h-[440px] min-w-0 flex-col rounded-control border border-line bg-surface">
          <ol ref={logRef} role="log" aria-live="polite" aria-relevant="additions" className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
            {messages.length === 0 && (
              <li className="text-sm text-ink-2">
                <p>{t("copilot.empty")}</p>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-3">
                  <Info aria-hidden className="size-4" />
                  {t("copilot.untrustedNote")}
                </p>
              </li>
            )}
            {messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} text={m.text} /> : <CopilotTurn key={m.id} message={m} currency={currency} />))}
            {chat.isPending && (
              <li className="flex items-center gap-2 text-sm text-ink-2" role="status">
                <span aria-hidden className="flex gap-1">
                  <span className="size-1.5 animate-pulse rounded-full bg-ink-3 motion-reduce:animate-none" />
                  <span className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:150ms] motion-reduce:animate-none" />
                  <span className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:300ms] motion-reduce:animate-none" />
                </span>
                {t("copilot.thinking")}
              </li>
            )}
          </ol>

          {chat.isError && (
            <div className="px-6 pb-3">
              <ErrorState error={chat.error} />
            </div>
          )}

          <div className="border-t border-line p-4">
            <div className="-mx-1 mb-3 flex flex-wrap gap-2 px-1" role="group" aria-label={t("copilot.suggestions")}>
              {prompts.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => send(p)}
                  disabled={chat.isPending}
                  className="h-8 shrink-0 rounded-full border border-line bg-canvas px-3 text-xs whitespace-nowrap text-ink-2 transition-colors duration-150 hover:border-control hover:text-ink disabled:opacity-50"
                >
                  {p}
                </button>
              ))}
            </div>
            <form onSubmit={onSubmit} className="flex items-end gap-2">
              <label htmlFor="copilot-input" className="sr-only">
                {t("copilot.inputLabel")}
              </label>
              <textarea
                id="copilot-input"
                ref={inputRef}
                rows={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(draft);
                  }
                }}
                placeholder={t("copilot.inputPlaceholder")}
                className="max-h-40 min-h-11 flex-1 resize-y rounded-control border border-control bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25"
              />
              <Button type="submit" variant="primary" size="lg" className="w-11 px-0" disabled={!draft.trim() || chat.isPending} aria-label={t("copilot.send")}>
                <ArrowUp aria-hidden weight="bold" className="size-5" />
              </Button>
            </form>
          </div>
        </section>

        <div className="min-w-0 xl:sticky xl:top-6 xl:self-start">
          <ProposalReceipt
            proposal={shownProposal}
            authorization={shownAuthorization}
            receipt={receipt}
            onConfirm={onConfirm}
            onExecute={onExecute}
            confirming={confirm.isPending}
            executing={execute.isPending}
            error={confirm.error ?? execute.error}
            blocked={blocked}
            onBack={() => inputRef.current?.focus()}
          />
        </div>
      </div>
    </>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <li className="flex justify-end">
      <div className="max-w-[65ch] rounded-control rounded-br-[2px] bg-ink px-4 py-3 text-sm text-white">
        <span className="sr-only">{t("copilot.you")}: </span>
        {text}
      </div>
    </li>
  );
}

function CopilotTurn({ message, currency }: { message: Message; currency: string }) {
  const reply = message.reply;
  const blockedAction = reply?.actions.find((a) => a.status === "BLOCKED");
  return (
    <li className="max-w-[72ch]">
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-3">
        <ChatText aria-hidden className="size-4" />
        {t("copilot.voice")}
      </p>
      <div className="rounded-control rounded-tl-[2px] border border-line bg-canvas px-4 py-3 text-[15px] leading-relaxed text-ink">
        {/* Plain text only: model output is never rendered as markup. */}
        <p className="whitespace-pre-line">{message.text}</p>
      </div>
      {reply?.blocked_reason && (
        <div className="mt-3">
          <VerdictBanner
            compact
            reason={reply.blocked_reason}
            currency={currency}
            authorized={blockedAction?.authorized_amount}
            requested={blockedAction?.requested_amount}
          />
        </div>
      )}
      {reply && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {reply.fallback_used ? (
            <StatusBadge tone="neutral">{t("copilot.replaced")}</StatusBadge>
          ) : reply.verification?.ok ? (
            <StatusBadge tone="positive" icon={SealCheck}>
              {t("copilot.verified")}
            </StatusBadge>
          ) : null}
          {reply.gate === "clarify" && <StatusBadge tone="warning">{t("copilot.clarify")}</StatusBadge>}
          {reply.gate === "read_only" && <StatusBadge tone="neutral">{t("copilot.readOnly")}</StatusBadge>}
          {reply.tools_called.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-ink-3">
              <Wrench aria-hidden className="size-3.5" />
              <span className="sr-only">{t("copilot.toolsUsed", { tools: reply.tools_called.join(", ") })}</span>
              <span aria-hidden className="font-mono">
                {reply.tools_called.join(" ")}
              </span>
            </span>
          )}
        </div>
      )}
    </li>
  );
}
