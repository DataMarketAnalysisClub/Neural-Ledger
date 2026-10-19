import { useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { ArrowUp, Camera, CheckCircle, File as FileIcon, FilePdf, FileXls, Info, MinusCircle, NotePencil, Paperclip, SealCheck, UploadSimple, WarningCircle, Wrench, XCircle } from "@phosphor-icons/react";
import {
  useChat,
  useConfirmExpense,
  useConfirmProposal,
  useCorrectReceipt,
  useExecute,
  useFinancialState,
  useIngestDocument,
  usePending,
  usePersona,
  type DocumentIngest,
  type ExpenseProposal,
  type ReceiptView,
} from "@/api/hooks";
import { ApiError, type ActionOutcome, type ChatReply } from "@/api/client";
import { ProposalReceipt, VerdictBanner } from "@/components/actions";
import { CopilotAvatar, type AvatarState } from "@/components/CopilotAvatar";
import { Button, ErrorState, Notice, PageHeader, StatusBadge, cn } from "@/components/ui";
import { t, tDynamic, tList } from "@/i18n";
import { formatMoney } from "@/lib/format";
import { useMediaQuery } from "@/lib/useMediaQuery";

/** The tallest the phone's input grows before it scrolls inside: about six lines. */
const PHONE_INPUT_MAX = 144;
/** The API refuses larger files; checked here too so a big photo fails at once, before it is sent. */
const MAX_DOCUMENT_BYTES = 15 * 1024 * 1024;
const DOCUMENT_TYPES = ".pdf,.xlsx,.png,.jpg,.jpeg,.webp,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/png,image/jpeg,image/webp";

type Proposal = NonNullable<ActionOutcome["proposal"]>;
type Authorization = NonNullable<ActionOutcome["authorization"]>;

/** What the user sent, shown back in their bubble: a photo as a thumbnail, any other file as its name. */
interface Attachment {
  name: string;
  kind: "image" | "pdf" | "sheet" | "file";
  url?: string; // an object URL of the photo, revoked when the conversation unmounts
}

function attachmentOf(file: File): Attachment {
  const lower = file.name.toLowerCase();
  if (file.type.startsWith("image/")) return { name: file.name, kind: "image", url: URL.createObjectURL(file) };
  if (file.type === "application/pdf" || lower.endsWith(".pdf")) return { name: file.name, kind: "pdf" };
  if (lower.endsWith(".xlsx")) return { name: file.name, kind: "sheet" };
  return { name: file.name, kind: "file" };
}

interface Message {
  id: number;
  role: "user" | "copilot" | "document";
  text: string;
  reply?: ChatReply;
  attachment?: Attachment;
  /** A file dropped on the copilot (ADR-039): its workflow, once the API answers. The file stays for a retry. */
  document?: { name: string; file?: File; result?: DocumentIngest; error?: unknown };
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
  const ingest = useIngestDocument();
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

  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const previews = useRef<string[]>([]);
  useEffect(() => () => previews.current.forEach((url) => URL.revokeObjectURL(url)), []);
  // A file dragged over the chat: the whole conversation is the drop zone, as in messaging apps.
  const [dragging, setDragging] = useState(false);
  const busyUploading = ingest.isPending || chat.isPending;
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const dropZone = {
    onDragEnter: (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); setDragging(true); } },
    onDragOver: (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = busyUploading ? "none" : "copy"; } },
    onDragLeave: (e: DragEvent) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file && !busyUploading) onDocument(file);
    },
  };
  const dropOverlay = dragging && (
    <div aria-hidden className="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center gap-2 rounded-control border-2 border-dashed border-accent bg-accent-soft/90 text-sm font-medium text-accent">
      <UploadSimple weight="bold" className="size-7" />
      {t("copilot.documents.drop")}
    </div>
  );

  /**
   * The file goes to the API, which decides what it is and runs the workflow; the steps it answers are shown as they
   * happened. Then the copilot is asked what changed, so every figure in its answer comes from the engine's tools.
   */
  function onDocument(file: File) {
    const attachment = attachmentOf(file);
    if (attachment.url) previews.current.push(attachment.url);
    const sentId = nextId.current++;
    const id = nextId.current++;
    setMessages((m) => [...m, { id: sentId, role: "user", text: t("copilot.documents.sent", { name: file.name }), attachment }, { id, role: "document", text: "", document: { name: file.name, file } }]);
    if (file.size > MAX_DOCUMENT_BYTES) {
      updateDocument(id, { name: file.name, file, error: new Error(t("statements.upload.tooLarge")) });
      return;
    }
    runDocument(id, file);
  }

  const updateDocument = (id: number, document: Message["document"]) => setMessages((m) => m.map((x) => (x.id === id ? { ...x, document } : x)));

  /** The workflow on one file; `kind` is the user's answer when the file was not recognized. */
  function runDocument(id: number, file: File, kind?: "receipt" | "statement") {
    updateDocument(id, { name: file.name, file });
    ingest.mutate(
      { file, kind },
      {
        onSuccess: (envelope) => {
          updateDocument(id, { name: file.name, file, result: envelope.data ?? undefined });
          send(t("copilot.documents.followUp"));
        },
        onError: (error) => updateDocument(id, { name: file.name, file, error }),
      },
    );
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
          <UserBubble key={m.id} text={m.text} attachment={m.attachment} />
        ) : m.role === "document" && m.document ? (
          <DocumentTurn
            key={m.id}
            document={m.document}
            currency={currency}
            busy={busyUploading}
            onKind={(kind) => m.document?.file && runDocument(m.id, m.document.file, kind)}
            onCorrected={(receipt) => {
              const doc = m.document;
              if (doc?.result) updateDocument(m.id, { ...doc, result: { ...doc.result, receipt } });
              send(t("copilot.documents.correctedFollowUp"));
            }}
          />
        ) : (
          <CopilotTurn
            key={m.id}
            message={m}
            currency={currency}
            avatarState={m.id === speakingId ? "responding" : "idle"}
            still={m.id !== lastCopilotId}
            onExpenseSaved={() => send(t("copilot.expense.followUp"))}
          />
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
        <input
          ref={fileInput}
          type="file"
          accept={DOCUMENT_TYPES}
          aria-label={t("copilot.documents.attach")}
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onDocument(file);
          }}
        />
        {/* On a phone the back camera opens straight away, for a photo of the receipt. */}
        {phone && (
          <>
            <input
              ref={cameraInput}
              type="file"
              accept="image/*"
              capture="environment"
              aria-label={t("copilot.documents.camera")}
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) onDocument(file);
              }}
            />
            <Button
              type="button"
              variant="secondary"
              size="lg"
              className="size-11 shrink-0 rounded-full px-0"
              disabled={busyUploading}
              onClick={() => cameraInput.current?.click()}
              aria-label={t("copilot.documents.camera")}
            >
              <Camera aria-hidden weight="bold" className="size-5" />
            </Button>
          </>
        )}
        <Button
          type="button"
          variant="secondary"
          size="lg"
          className={cn("w-11 shrink-0 px-0", phone && "size-11 rounded-full")}
          disabled={busyUploading}
          busy={ingest.isPending}
          onClick={() => fileInput.current?.click()}
          aria-label={t("copilot.documents.attach")}
          title={t("copilot.documents.attachHint")}
        >
          {!ingest.isPending && <Paperclip aria-hidden weight="bold" className="size-5" />}
        </Button>
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
          // On a phone the camera and the clip leave the box narrow: a short prompt keeps it to one line.
          placeholder={phone ? t("copilot.inputLabel") : t("copilot.inputPlaceholder")}
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
        <section aria-label={t("copilot.title")} {...dropZone} className="relative flex h-[calc(100dvh-var(--phone-header-h,6.5rem))] min-w-0 flex-col bg-surface">
          {dropOverlay}
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
        <section aria-label={t("copilot.title")} {...dropZone} className="relative flex h-[calc(100dvh-15rem)] min-h-[440px] min-w-0 flex-col rounded-control border border-line bg-surface">
          {dropOverlay}
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

/**
 * Text that folds when it is long, behind a Show more button, as messaging apps do. It wraps anywhere, so a token
 * with no spaces can never push the bubble wider than the screen.
 */
function FoldableText({ text, maxChars, maxLines, tone }: { text: string; maxChars: number; maxLines: number; tone: "dark" | "light" }) {
  const [open, setOpen] = useState(false);
  const long = text.length > maxChars || text.split("\n").length > maxLines;
  return (
    <>
      <p className={cn("whitespace-pre-line [overflow-wrap:anywhere]", long && !open && "line-clamp-6")}>{text}</p>
      {long && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className={cn("mt-1.5 text-sm font-medium underline underline-offset-2", tone === "dark" ? "text-white/80 hover:text-white" : "text-accent hover:text-accent-hover")}
        >
          {open ? t("copilot.showLess") : t("copilot.showMore")}
        </button>
      )}
    </>
  );
}

const FILE_ICON = { pdf: FilePdf, sheet: FileXls, file: FileIcon, image: FileIcon } as const;

function UserBubble({ text, attachment }: { text: string; attachment?: Attachment }) {
  if (attachment) {
    const Icon = FILE_ICON[attachment.kind];
    return (
      <li className="flex justify-end">
        <figure className="max-w-[min(20rem,85%)] min-w-0 overflow-hidden rounded-control rounded-br-[2px] bg-ink text-sm text-white">
          <span className="sr-only">{t("copilot.you")}: {text}</span>
          {attachment.url ? (
            <img src={attachment.url} alt={t("copilot.documents.preview", { name: attachment.name })} className="block max-h-72 w-full object-cover" />
          ) : (
            <div aria-hidden className="flex items-center gap-3 px-4 pt-3">
              <Icon weight="duotone" className="size-9 shrink-0" />
            </div>
          )}
          <figcaption aria-hidden className="px-4 py-2.5 [overflow-wrap:anywhere]">{attachment.name}</figcaption>
        </figure>
      </li>
    );
  }
  return (
    <li className="flex justify-end">
      <div className="max-w-[min(65ch,100%)] min-w-0 rounded-control rounded-br-[2px] bg-ink px-4 py-3 text-sm text-white [overflow-wrap:anywhere]">
        <span className="sr-only">{t("copilot.you")}: </span>
        <FoldableText text={text} maxChars={360} maxLines={8} tone="dark" />
      </div>
    </li>
  );
}

function CopilotTurn({
  message,
  currency,
  avatarState,
  still,
  onExpenseSaved,
}: {
  message: Message;
  currency: string;
  avatarState: AvatarState;
  still: boolean;
  onExpenseSaved: () => void;
}) {
  const reply = message.reply;
  const blockedAction = reply?.actions.find((a) => a.status === "BLOCKED");
  return (
    <li className="max-w-[72ch]">
      {/* Like a messaging app: the avatar sits to the left of the reply, level with the bottom of the bubble. */}
      <div className="flex items-end gap-2.5">
        <CopilotAvatar state={avatarState} still={still} className="size-7 sm:size-8" />
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-ink-3">{t("copilot.voice")}</p>
          <div className="rounded-control rounded-bl-[2px] border border-accent/20 bg-accent-soft px-4 py-3 text-[15px] leading-relaxed text-ink [overflow-wrap:anywhere]">
            {/* Plain text only: model output is never rendered as markup. */}
            <FoldableText text={message.text} maxChars={1100} maxLines={14} tone="light" />
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
      {reply?.pending_expense && <ExpenseCard key={reply.pending_expense.proposal_id} expense={reply.pending_expense} currency={currency} onSaved={onExpenseSaved} />}
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

const STEP_ICON = { done: CheckCircle, warning: WarningCircle, skipped: MinusCircle, failed: XCircle } as const;
const STEP_TONE = { done: "text-accent", warning: "text-warning", skipped: "text-ink-3", failed: "text-danger" } as const;
/** Steps whose answer came from a model: the card names it, so the AI's part is visible, never hidden. */
const MODEL_STEPS = new Set(["route", "categorize"]);
const RULE_ANSWERS = new Set(["rules", "format"]); // decided by a fixed rule, not a model: nothing to name

/** The workflow the API ran on a dropped file, one step at a time. Labels only: the copilot's reply carries the numbers. */
function DocumentTurn({
  document,
  currency,
  busy,
  onKind,
  onCorrected,
}: {
  document: NonNullable<Message["document"]>;
  currency: string;
  busy: boolean;
  onKind: (kind: "receipt" | "statement") => void;
  onCorrected: (receipt: ReceiptView) => void;
}) {
  const { name, result, error } = document;
  const receipt = result?.kind === "receipt" ? result.receipt : null;
  return (
    <li className="max-w-[72ch]">
      <div className="flex items-end gap-2.5">
        <CopilotAvatar state={result || error ? "idle" : "thinking"} still={Boolean(result || error)} className="size-7 sm:size-8" />
        <div className="min-w-0 flex-1 rounded-control rounded-bl-[2px] border border-line bg-canvas px-4 py-3 text-sm">
          <p className="text-xs font-medium text-ink-3 [overflow-wrap:anywhere]">{t("copilot.documents.title", { name })}</p>
          {!result && !error && (
            <p role="status" className="mt-2 text-ink-2">
              {t("copilot.documents.reading", { name })}
            </p>
          )}
          {error !== undefined && (
            <div className="mt-2">
              {needsOcr(error) ? <Notice tone="warning" title={t("copilot.documents.needsOcr")} /> : <ErrorState error={error} />}
              {unrecognized(error) && document.file && (
                <div className="mt-3" role="group" aria-label={t("copilot.documents.whatIsIt")}>
                  <p className="text-ink-2">{t("copilot.documents.whatIsIt")}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => onKind("receipt")}>
                      {t("copilot.documents.isReceipt")}
                    </Button>
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => onKind("statement")}>
                      {t("copilot.documents.isStatement")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
          {result && (
            <ol className="mt-2 space-y-1.5" aria-label={t("copilot.documents.title", { name })}>
              {result.steps.map((step, i) => {
                const Icon = STEP_ICON[step.status];
                const value = stepValue(result, step, currency);
                return (
                  <li
                    key={`${step.key}-${i}`}
                    className="flex animate-[rise_320ms_var(--ease-out)_both] items-start gap-2 motion-reduce:animate-none"
                    style={{ animationDelay: `${i * 140}ms` }}
                  >
                    <Icon aria-hidden weight="fill" className={cn("mt-0.5 size-4 shrink-0", STEP_TONE[step.status])} />
                    <span className="min-w-0 [overflow-wrap:anywhere]">
                      <span className="font-medium text-ink">{tDynamic("copilot.documents.steps", step.key)}</span>
                      {value && <span className="text-ink-2">: {value}</span>}
                      {step.by && MODEL_STEPS.has(step.key) && !RULE_ANSWERS.has(step.by) && (
                        <span className="ml-1.5 font-mono text-xs text-ink-3">{t("copilot.documents.by", { by: step.by })}</span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {receipt && <ReceiptFix key={receipt.receipt_id} receipt={receipt} currency={currency} onCorrected={onCorrected} />}
        </div>
      </div>
    </li>
  );
}

/** What the reader could not read, or read with doubt: the copilot asks, and the user types it here. */
function needsFix(r: ReceiptView): boolean {
  return !r.verified || r.total === null || r.issued_on === null || (r.source === "ocr" && !r.stamped && !r.corrected);
}

/**
 * The user's correction of a receipt (ADR-039). Opens by itself when something is missing; otherwise behind a button.
 * What the user types goes to the API as typed; nothing here computes or guesses a value.
 */
function ReceiptFix({ receipt, currency, onCorrected }: { receipt: ReceiptView; currency: string; onCorrected: (r: ReceiptView) => void }) {
  const correct = useCorrectReceipt();
  const missing = !receipt.verified || receipt.total === null || receipt.issued_on === null;
  const [open, setOpen] = useState(missing);
  const [total, setTotal] = useState(receipt.total !== null ? String(receipt.total) : "");
  const [issuedOn, setIssuedOn] = useState(receipt.issued_on ?? "");
  if (receipt.corrected && !missing && !open) return <p className="mt-3 text-xs text-ink-3">{t("copilot.documents.fix.done")}</p>;
  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn("mt-3 text-xs font-medium underline underline-offset-2", needsFix(receipt) ? "text-warning" : "text-accent hover:text-accent-hover")}
      >
        {receipt.total !== null ? t("copilot.documents.fix.offer", { amount: formatMoney(receipt.total, currency) }) : t("copilot.documents.fix.title")}
      </button>
    );
  const digits = total.replace(/[^\d]/g, "");
  return (
    <form
      className="mt-3 rounded-control border border-line bg-surface p-3"
      aria-label={t("copilot.documents.fix.title")}
      onSubmit={(e) => {
        e.preventDefault();
        const fix: { total?: number; issued_on?: string } = {};
        if (digits && Number(digits) !== receipt.total) fix.total = Number(digits);
        if (issuedOn && issuedOn !== receipt.issued_on) fix.issued_on = issuedOn;
        if (!fix.total && !fix.issued_on) {
          // Confirming what was read is a correction too: the user vouches for it.
          if (digits) fix.total = Number(digits);
          else if (issuedOn) fix.issued_on = issuedOn;
        }
        correct.mutate(
          { receiptId: receipt.receipt_id, ...fix },
          {
            onSuccess: (envelope) => {
              setOpen(false);
              if (envelope.data) onCorrected(envelope.data);
            },
          },
        );
      }}
    >
      <p className="font-medium text-ink">{missing ? t("copilot.documents.fix.ask") : t("copilot.documents.fix.title")}</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="text-xs text-ink-2">
          {t("copilot.documents.fix.date")}
          <input
            type="date"
            value={issuedOn}
            onChange={(e) => setIssuedOn(e.target.value)}
            className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink"
          />
        </label>
        <label className="text-xs text-ink-2">
          {t("copilot.documents.fix.total", { currency })}
          <input
            inputMode="numeric"
            value={total}
            onChange={(e) => setTotal(e.target.value)}
            placeholder="12990"
            className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink"
          />
        </label>
      </div>
      {correct.isError && (
        <div className="mt-2">
          <ErrorState error={correct.error} />
        </div>
      )}
      <div className="mt-3 flex gap-2">
        <Button type="submit" size="sm" variant="primary" busy={correct.isPending} disabled={correct.isPending || (!digits && !issuedOn)}>
          {t("copilot.documents.fix.save")}
        </Button>
        {!missing && (
          <Button type="button" size="sm" variant="quiet" onClick={() => setOpen(false)}>
            {t("copilot.documents.fix.cancel")}
          </Button>
        )}
      </div>
      <p className="mt-2 text-xs text-ink-3">{t("copilot.documents.fix.note")}</p>
    </form>
  );
}

/** The workflow answered that the file is neither a receipt nor a statement it could recognize. */
function unrecognized(error: unknown): boolean {
  return error instanceof ApiError && error.detail.field === "file" && Boolean(error.detail.allowed?.includes("receipt"));
}

/** A photo on a server without the `ocr` extra: say what to do instead of naming the missing part. */
function needsOcr(error: unknown): boolean {
  return error instanceof ApiError && Boolean(error.detail.missing?.includes("document_reader"));
}

function stepValue(result: DocumentIngest, step: DocumentIngest["steps"][number], currency: string): string | null {
  if (step.value === null) return null;
  if (step.key === "spending") return t("copilot.documents.perDay", { amount: formatMoney(Number(step.value), currency) });
  if (step.key === "categorize") {
    if (result.kind === "receipt") return tDynamic("statements.categories", step.value);
    return /^\d+$/.test(step.value) ? t("copilot.documents.posted", { count: step.value }) : tDynamic("copilot.documents.values", step.value);
  }
  if (step.key === "redact" && result.kind === "statement") return null;
  return tDynamic("copilot.documents.values", step.value);
}

const EXPENSE_CATEGORIES = ["groceries", "dining", "transport", "health", "shopping", "utilities", "entertainment", "other"] as const;

/**
 * An expense the copilot prepared from what the user said (ADR-039). The amount is shown as prepared and is not
 * editable here; the user completes what the copilot could not tell (cash or card, the category) and confirms.
 * Nothing is stored until they do.
 */
function ExpenseCard({ expense, currency, onSaved }: { expense: ExpenseProposal; currency: string; onSaved: () => void }) {
  const confirm = useConfirmExpense();
  const [payment, setPayment] = useState<"cash" | "card" | "">(expense.payment === "unknown" ? "" : (expense.payment as "cash" | "card"));
  const [category, setCategory] = useState(expense.category === "uncategorized" ? "" : expense.category);
  const [spentOn, setSpentOn] = useState(expense.spent_on);
  const saved = confirm.isSuccess;
  return (
    <form
      className="mt-3 rounded-control border border-accent/30 bg-surface p-4 text-sm"
      aria-label={t("copilot.expense.title")}
      onSubmit={(e) => {
        e.preventDefault();
        if (!payment) return;
        confirm.mutate(
          {
            proposalId: expense.proposal_id,
            payment,
            ...(category ? { category: category as (typeof EXPENSE_CATEGORIES)[number] } : {}),
            ...(spentOn !== expense.spent_on ? { spent_on: spentOn } : {}),
          },
          { onSuccess: () => onSaved() },
        );
      }}
    >
      <p className="text-xs font-medium text-ink-3">{t("copilot.expense.title")}</p>
      <p className="mt-1 text-xl font-semibold text-ink">{formatMoney(expense.amount, currency)}</p>
      <p className="text-ink-2 [overflow-wrap:anywhere]">{expense.description.untrusted_text}</p>
      {saved ? (
        <p role="status" className="mt-3 flex items-center gap-1.5 font-medium text-positive">
          <CheckCircle aria-hidden weight="fill" className="size-4" />
          {t("copilot.expense.saved")}
        </p>
      ) : (
        <>
          <fieldset className="mt-3">
            <legend className={cn("text-xs", expense.missing.includes("payment") ? "font-medium text-warning" : "text-ink-2")}>{t("copilot.expense.payment")}</legend>
            <div className="mt-1 flex gap-2">
              {(["cash", "card"] as const).map((value) => (
                <label
                  key={value}
                  className={cn(
                    "cursor-pointer rounded-full border px-3 py-1.5 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                    payment === value ? "border-accent bg-accent-soft font-medium text-ink" : "border-line text-ink-2",
                  )}
                >
                  <input type="radio" name={`payment-${expense.proposal_id}`} value={value} checked={payment === value} onChange={() => setPayment(value)} className="sr-only" />
                  {t(`copilot.expense.${value}`)}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className={cn("text-xs", expense.missing.includes("category") ? "font-medium text-warning" : "text-ink-2")}>
              {t("copilot.expense.category")}
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink">
                <option value="">{t("copilot.expense.pick")}</option>
                {EXPENSE_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {tDynamic("statements.categories", c)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-2">
              {t("copilot.expense.date")}
              <input type="date" value={spentOn} onChange={(e) => setSpentOn(e.target.value)} className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink" />
            </label>
          </div>
          {confirm.isError && (
            <div className="mt-2">
              <ErrorState error={confirm.error} />
            </div>
          )}
          <Button type="submit" size="sm" variant="primary" className="mt-3" busy={confirm.isPending} disabled={!payment || confirm.isPending}>
            {t("copilot.expense.confirm")}
          </Button>
          <p className="mt-2 text-xs text-ink-3">{payment === "cash" ? t("copilot.expense.cashNote") : t("copilot.expense.cardNote")}</p>
        </>
      )}
    </form>
  );
}
