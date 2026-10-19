import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { ArrowUp, Info, NotePencil, SealCheck, Wrench } from "@phosphor-icons/react";
import { useChat, useConfirmProposal, useExecute, useFinancialState, usePending, usePersona } from "@/api/hooks";
import { ApiError, type ActionOutcome, type ChatReply } from "@/api/client";
import { ProposalReceipt, VerdictBanner } from "@/components/actions";
import { CopilotAvatar, type AvatarState } from "@/components/CopilotAvatar";
import { Button, ErrorState, PageHeader, StatusBadge, cn } from "@/components/ui";
import { t, tList } from "@/i18n";
import { useMediaQuery } from "@/lib/useMediaQuery";

/** The tallest the phone's input grows before it scrolls inside: about six lines. */
const PHONE_INPUT_MAX = 144;

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
  // The avatar answers for a moment when a reply lands, then rests.
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const speakingTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(speakingTimer.current), []);
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
    // Scroll the log only: scrollIntoView would also scroll the window.
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, chat.isPending]);

  // Below xl the receipt sits under the chat: bring a new proposal into view so the terms are never missed.
  const receiptEl = useRef<HTMLElement | null>(null);
  const receiptRef = (el: HTMLElement | null) => { receiptEl.current = el; };
  const proposalId = proposal?.proposal_id;
  useEffect(() => {
    if (!proposalId || typeof window.matchMedia !== "function" || !window.matchMedia("(max-width: 1279px)").matches) return;
    receiptEl.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [proposalId]);

  function send(text: string) {
    const message = text.trim();
    if (!message || chat.isPending) return;
    setMessages((m) => [...m, { id: nextId.current++, role: "user", text: message }]);
    setDraft("");
    chat.mutate(message, {
      onSuccess: (reply) => {
        const id = nextId.current++;
        setMessages((m) => [...m, { id, role: "copilot", text: reply.text, reply }]);
        setSpeakingId(id);
        clearTimeout(speakingTimer.current);
        speakingTimer.current = setTimeout(() => setSpeakingId(null), 1600);
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

  const lastCopilotId = [...messages].reverse().find((m) => m.role === "copilot")?.id;
  const blocked = useMemo(() => outcomeFrom(confirm.error) ?? outcomeFrom(execute.error), [confirm.error, execute.error]);
  const prompts = tList("copilot.prompts");

  // Below lg the screen is the chat and the box to write in, between the header and the bottom bar; the receipt
  // then joins the conversation instead of sitting in a panel of its own.
  const phone = useMediaQuery("(max-width: 1023px)");
  const showReceipt = Boolean(shownProposal || shownAuthorization || receipt);

  // Like a messaging app: the box grows with the message, upward (the chat above gives it room), up to a limit and
  // then scrolls inside. The chat stays at its end if it was there, so the last message is never pushed out of sight.
  useLayoutEffect(() => {
    const box = inputRef.current;
    if (!phone || !box) return;
    const log = logRef.current;
    const atEnd = !log || log.scrollHeight - log.scrollTop - log.clientHeight < 48;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, PHONE_INPUT_MAX)}px`;
    box.style.overflowY = box.scrollHeight > PHONE_INPUT_MAX ? "auto" : "hidden";
    if (log && atEnd) log.scrollTop = log.scrollHeight;
  }, [draft, phone]);
  const receiptPanel = (
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
  );

  const log = (
    <ol ref={logRef} role="log" aria-live="polite" aria-relevant="additions" className={cn("relative min-h-0 flex-1 space-y-6 overflow-y-auto p-4 sm:p-6", phone && "pt-16")}>
      {messages.length === 0 && (
        <li className="text-sm text-ink-2">
          <CopilotAvatar className="mb-3 size-10" />
          <p>{t("copilot.empty")}</p>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-3">
            <Info aria-hidden className="size-4" />
            {t("copilot.untrustedNote")}
          </p>
        </li>
      )}
      {messages.map((m) =>
        m.role === "user" ? (
          <UserBubble key={m.id} text={m.text} />
        ) : (
          <CopilotTurn key={m.id} message={m} currency={currency} avatarState={m.id === speakingId ? "responding" : "idle"} still={m.id !== lastCopilotId} />
        ),
      )}
      {chat.isPending && (
        <li className="flex items-end gap-2.5 text-sm text-ink-2" role="status">
          <CopilotAvatar state="thinking" className="size-7 sm:size-8" />
          <span className="rounded-control rounded-bl-[2px] border border-accent/20 bg-accent-soft px-4 py-2.5">{t("copilot.thinking")}</span>
        </li>
      )}
      {phone && showReceipt && (
        <li ref={receiptRef} className="scroll-mt-4">
          {receiptPanel}
        </li>
      )}
    </ol>
  );

  const composer = (
    <div className={cn("border-t border-line p-3 sm:p-4", phone && "pb-[calc(var(--phone-bar-h)+1.5rem)]")}>
      {/* One scrolling row on a phone, so the suggestions never push the composer off screen; once the conversation starts they leave. */}
      {(!phone || messages.length === 0) && (
        <div className="-mx-3 mb-3 flex snap-x gap-2 overflow-x-auto px-3 pb-1 [scrollbar-width:none] sm:-mx-1 sm:flex-wrap sm:overflow-visible sm:px-1 sm:pb-0 [&::-webkit-scrollbar]:hidden" role="group" aria-label={t("copilot.suggestions")}>
          {prompts.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => send(p)}
              disabled={chat.isPending}
              className="h-9 shrink-0 snap-start rounded-full border border-line bg-canvas px-3 text-xs whitespace-nowrap text-ink-2 transition-colors duration-150 hover:border-control hover:text-ink disabled:opacity-50"
            >
              {p}
            </button>
          ))}
        </div>
      )}
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
            // A phone keyboard has no Shift: there Enter is a new line and the arrow button sends.
            if (e.key === "Enter" && !e.shiftKey && !phone) {
              e.preventDefault();
              send(draft);
            }
          }}
          placeholder={t("copilot.inputPlaceholder")}
          className={cn("min-h-11 flex-1 border border-control bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25", phone ? "resize-none rounded-3xl px-4" : "max-h-40 resize-y rounded-control")}
        />
        <Button type="submit" variant="primary" size="lg" className={cn("w-11 px-0", phone && "size-11 rounded-full")} disabled={!draft.trim() || chat.isPending} aria-label={t("copilot.send")}>
          <ArrowUp aria-hidden weight="bold" className="size-5" />
        </Button>
      </form>
    </div>
  );

  if (phone) {
    return (
      <div className="-mx-4 -my-6 sm:-mx-6">
        <h1 id="page-title" className="sr-only">{t("copilot.title")}</h1>
        <section aria-label={t("copilot.title")} className="relative flex h-[calc(100dvh-var(--phone-header-h,6.5rem))] min-w-0 flex-col bg-surface">
          <Button variant="quiet" size="sm" onClick={newSession} aria-label={t("copilot.newConversation")} className="absolute top-2 right-2 z-10 size-10 rounded-full bg-surface/90 px-0 ring-1 ring-line">
            <NotePencil aria-hidden className="size-5" />
          </Button>
          {log}
          {chat.isError && (
            <div className="px-4 pb-3">
              <ErrorState error={chat.error} />
            </div>
          )}
          {composer}
        </section>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title={t("copilot.title")}
        subtitle={<span className="hidden sm:inline">{t("copilot.subtitle")}</span>}
        actions={
          <Button variant="secondary" size="sm" onClick={newSession}>
            <NotePencil aria-hidden className="size-4" />
            {t("copilot.newConversation")}
          </Button>
        }
      />

      <div className="grid gap-10 xl:grid-cols-[1fr_400px]">
        <section aria-label={t("copilot.title")} className="flex h-[calc(100dvh-15rem)] min-h-[440px] min-w-0 flex-col rounded-control border border-line bg-surface">
          {log}
          {chat.isError && (
            <div className="px-6 pb-3">
              <ErrorState error={chat.error} />
            </div>
          )}
          {composer}
        </section>

        <div ref={receiptRef} className="min-w-0 scroll-mt-28 xl:sticky xl:top-6 xl:self-start">
          {receiptPanel}
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

function CopilotTurn({ message, currency, avatarState, still }: { message: Message; currency: string; avatarState: AvatarState; still: boolean }) {
  const reply = message.reply;
  const blockedAction = reply?.actions.find((a) => a.status === "BLOCKED");
  return (
    <li className="max-w-[72ch]">
      {/* Like a messaging app: the avatar sits to the left of the reply, level with the bottom of the bubble. */}
      <div className="flex items-end gap-2.5">
        <CopilotAvatar state={avatarState} still={still} className="size-7 sm:size-8" />
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-ink-3">{t("copilot.voice")}</p>
          <div className="rounded-control rounded-bl-[2px] border border-accent/20 bg-accent-soft px-4 py-3 text-[15px] leading-relaxed text-ink">
            {/* Plain text only: model output is never rendered as markup. */}
            <p className="whitespace-pre-line">{message.text}</p>
          </div>
        </div>
      </div>
      <div className="pl-[2.375rem] sm:pl-[2.625rem]">
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
      </div>
    </li>
  );
}
