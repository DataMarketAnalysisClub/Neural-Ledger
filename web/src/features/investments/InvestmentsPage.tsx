import { useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowsClockwise, LinkBreak, Trash, UploadSimple } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import {
  useHealth,
  useIngestDocument,
  useInvestmentLink,
  useInvestments,
  useLinkInvestments,
  useRemoveInvestmentDocuments,
  useSyncInvestments,
  useUnlinkInvestments,
  type DocumentIngest,
  type InvestmentLinkOutcome,
  type InvestmentOverview,
} from "@/api/hooks";
import { Button, ErrorState, Loading, Notice, PageHeader, ScrollBox, Section, StatusBadge, cn, describeError, stickyHead } from "@/components/ui";
import { useAuth } from "@/features/auth/AuthProvider";
import { t, tDynamic, type MessageKey } from "@/i18n";
import { formatDate, formatMoney, formatNumber, formatPercent } from "@/lib/format";
import { PROVIDER_GROUPS, PROVIDERS } from "./providers";

/**
 * The user's investments (ADR-044), in two tabs. Statements, the path in use: the user drops the PDFs their provider
 * issues (Fintual's are the ones read today), the API reads them (never a model), checks that they add up and keeps
 * only what does; the copilot then reads the same figures. Real-time connection is in development (Fintual refuses
 * third-party reads): the tab says what it is for and shows its form disabled unless VITE_INVESTMENT_LINKING=on.
 * Every figure is the API's: the page formats, it never computes. Goal names and file names are the user's own text
 * and render as plain text.
 */

type AccountLink = NonNullable<InvestmentLinkOutcome["link"]>;
type Upload = { id: number; name: string; result?: DocumentIngest; error?: unknown };

const MAX_BYTES = 15 * 1024 * 1024;
const fieldClass = "h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 disabled:cursor-not-allowed disabled:opacity-60";

const STATUS_ERRORS: Partial<Record<InvestmentLinkOutcome["status"], MessageKey>> = {
  ACCESS_REJECTED: "investments.errors.accessRejected",
  READ_REFUSED: "investments.errors.readRefused",
  PROVIDER_UNAVAILABLE: "investments.errors.unavailable",
  RELINK_REQUIRED: "investments.errors.relink",
  CONFLICT: "investments.errors.conflict",
  READ_ONLY: "investments.errors.readOnly",
};
const FIELD_ERRORS: Partial<Record<string, MessageKey>> = {
  email: "investments.errors.email",
  password: "investments.errors.password",
  consent: "investments.errors.consent",
};

/** The API answers in English; its statuses and fields are translated here. Nothing the user typed is repeated. */
function linkError(error: unknown): string {
  if (error instanceof ApiError) {
    const { status, field } = error.detail;
    const key = (field ? FIELD_ERRORS[field] : undefined) ?? (status ? STATUS_ERRORS[status as InvestmentLinkOutcome["status"]] : undefined);
    if (key) return t(key);
  }
  return describeError(error);
}

const TOO_LARGE = "too-large"; // checked here before anything is sent
const UNSUPPORTED = "unsupported";

function uploadError(error: unknown): string {
  if (error === TOO_LARGE) return t("investments.import.tooLarge");
  if (error === UNSUPPORTED) return t("investments.import.unsupported");
  if (error instanceof ApiError) {
    if (error.detail.field === "kind") return t("investments.import.readOnly");
    if (error.detail.field === "file") return t("investments.import.unsupported");
    if (error.httpStatus === 413) return t("investments.import.tooLarge");
  }
  return describeError(error);
}

// ---- import: the path in use -------------------------------------------------------------------

function ImportDocuments() {
  const input = useRef<HTMLInputElement>(null);
  const next = useRef(0);
  const ingest = useIngestDocument();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const busy = uploads.some((u) => u.result === undefined && u.error === undefined);

  const update = (id: number, change: Partial<Upload>) => setUploads((list) => list.map((u) => (u.id === id ? { ...u, ...change } : u)));

  /** One file after the other, in the order given: what the copilot knows changes as each one is kept. */
  async function importAll(files: File[]) {
    const queued = files.map((file) => ({ id: next.current++, name: file.name, file }));
    setUploads((list) => [...list, ...queued.map(({ id, name }) => ({ id, name }))]);
    for (const { id, file } of queued) {
      if (file.size > MAX_BYTES) {
        update(id, { error: TOO_LARGE });
        continue;
      }
      try {
        const envelope = await ingest.mutateAsync({ file, kind: "investment" });
        update(id, envelope.data ? { result: envelope.data } : { error: UNSUPPORTED });
      } catch (error) {
        update(id, { error });
      }
    }
  }

  function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // choosing the same file again still imports it
    if (files.length) void importAll(files);
  }

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");

  return (
    <Section id="import" title={t("investments.import.title")} className="max-w-3xl">
      <p className="text-sm text-ink-2">{t("investments.import.intro")}</p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
        <li>{t("investments.import.statement")}</li>
        <li>{t("investments.import.certificate")}</li>
      </ul>
      <div
        onDragOver={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          if (!hasFiles(event)) return;
          event.preventDefault();
          setDragging(false);
          if (!busy) void importAll([...event.dataTransfer.files]);
        }}
        className={cn(
          "mt-5 flex flex-col items-center rounded-control border-2 border-dashed px-4 py-8 text-center transition-colors",
          dragging ? "border-accent bg-accent-soft" : "border-line bg-surface",
        )}
      >
        <UploadSimple aria-hidden weight="bold" className={cn("size-7", dragging ? "text-accent" : "text-ink-3")} />
        <p className="mt-2 text-sm font-medium text-ink">{t("investments.import.drop")}</p>
        <p className="mt-1 text-xs text-ink-3">{t("investments.import.formats")}</p>
        <p className="mt-0.5 text-xs text-ink-3">{t("investments.import.supported")}</p>
        <input ref={input} type="file" accept=".pdf,application/pdf" multiple onChange={onFiles} aria-label={t("investments.import.choose")} className="sr-only" tabIndex={-1} />
        <Button className="mt-4" variant="secondary" busy={busy} disabled={busy} onClick={() => input.current?.click()}>
          {t("investments.import.choose")}
        </Button>
      </div>
      <p className="mt-3 text-xs text-ink-3">{t("investments.import.privacy")}</p>
      {uploads.length > 0 && (
        <ul className="mt-5 space-y-3" aria-live="polite">
          {uploads.map((upload) => (
            <UploadRow key={upload.id} upload={upload} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function UploadRow({ upload }: { readonly upload: Upload }) {
  const { name, result, error } = upload;
  if (result === undefined && error === undefined) {
    return <li role="status" className="text-sm text-ink-2">{t("investments.import.reading", { name })}</li>;
  }
  const imported = result?.investment;
  if (!imported) return <li><Notice tone="danger" title={name}>{uploadError(error)}</Notice></li>;
  const { document } = imported;
  const what = document.as_of
    ? t(document.kind === "holdings" ? "investments.import.holdings" : "investments.import.movements", { date: formatDate(document.as_of) })
    : t("investments.import.unknownDay");
  const title = `${name}: ${what}`;
  if (!document.verified) {
    const reason = document.issues.map((issue) => tDynamic("investments.import.issues", issue.code)).join("; ");
    return <li><Notice tone="warning" title={title}>{t("investments.import.unverified", { reason })}</Notice></li>;
  }
  if (imported.duplicate) return <li><Notice tone="neutral" title={title}>{t("investments.import.duplicate")}</Notice></li>;
  return <li><Notice tone="positive" title={title}>{t("investments.import.verified", { count: document.rows })}</Notice></li>;
}

// ---- what the copilot knows ---------------------------------------------------------------------

function Figure({ label, value, note }: { readonly label: string; readonly value: string; readonly note?: string }) {
  return (
    <div>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="num mt-1 text-xl font-semibold text-ink">{value}</dd>
      {note && <dd className="mt-0.5 text-xs text-ink-3">{note}</dd>}
    </div>
  );
}

function Portfolio() {
  const query = useInvestments(true);
  const remove = useRemoveInvestmentDocuments();
  const [confirming, setConfirming] = useState(false);
  if (query.isPending) return <Loading className="mt-10 max-w-3xl" />;
  if (query.isError) return <div className="mt-10"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  const data = query.data?.data;
  if (!data) return remove.isSuccess ? <div className="mt-8 max-w-3xl"><Notice tone="positive" title={t("investments.overview.forgotten")} /></div> : null;
  const currency = data.currency;
  const statement = data.source === "statement";
  const loss = data.total_gain !== null && data.total_gain < 0;
  const c = data.contributions;

  return (
    <Section id="holdings" title={t("investments.overview.title")} subtitle={t("investments.overview.asOf", { date: formatDate(data.as_of) })}
      className="mt-10 border-t border-line pt-10"
      aside={<Button asChild variant="secondary" size="sm"><Link to="/copilot">{t("investments.overview.askCopilot")}</Link></Button>}>
      <div className="max-w-3xl space-y-3 empty:hidden">
        {data.stale && <Notice tone="warning" title={t(statement ? "investments.overview.staleStatement" : "investments.overview.stale")} />}
        {statement && data.total_value === null && <Notice tone="neutral" title={t("investments.overview.noBalance")} />}
        {statement && c === null && <Notice tone="neutral" title={t("investments.overview.noHistory")} />}
        {c !== null && !c.complete && <Notice tone="warning" title={t("investments.overview.partial")} />}
        {data.documents_agree === false && <Notice tone="warning" title={t("investments.overview.disagree")} />}
      </div>
      <dl className="mt-6 grid gap-6 sm:grid-cols-3">
        {data.total_value !== null && <Figure label={t("investments.overview.total")} value={formatMoney(data.total_value, currency)} />}
        {data.total_deposited !== null && <Figure label={t("investments.overview.deposited")} value={formatMoney(data.total_deposited, currency)} />}
        {data.total_gain !== null && (
          <Figure
            label={t(loss ? "investments.overview.loss" : "investments.overview.gain")}
            value={formatMoney(data.total_gain, currency, { signed: true })}
            note={data.gain_pct !== null ? t("investments.overview.gainPct", { pct: formatPercent(data.gain_pct / 100) }) : undefined}
          />
        )}
      </dl>
      {!statement && data.total_gain === null && data.goals.length > 0 && <p className="mt-4 text-sm text-ink-2">{t("investments.overview.noDeposits")}</p>}
      {c && (
        <div className="mt-8 max-w-3xl">
          <h3 className="text-base font-semibold text-ink">{t("investments.overview.contributions")}</h3>
          <p className="mt-2 text-sm text-ink-2">
            {t("investments.overview.habit", {
              from: formatDate(c.first_day), to: formatDate(c.last_day), contributed: formatMoney(c.contributed, currency), count: c.contributions,
              withdrawn: formatMoney(c.withdrawn, currency), average: formatMoney(c.monthly_average, currency), active: c.active_months, months: c.months,
            })}
            {c.last_contribution && <> {t("investments.overview.lastContribution", { date: formatDate(c.last_contribution) })}</>}
          </p>
        </div>
      )}
      {data.funds.length > 0 && <Funds data={data} />}
      {data.goals.length > 0 ? <Goals data={data} /> : !statement && <p className="mt-6 text-sm text-ink-2">{t("investments.overview.empty")}</p>}
      <p className="mt-4 max-w-3xl text-xs text-ink-3">{t(statement ? "investments.overview.fromStatement" : "investments.overview.asReported")}</p>
      {statement && (
        <div className="mt-6 max-w-prose">
          {!confirming ? (
            <Button variant="quiet" onClick={() => { setConfirming(true); remove.reset(); }}>
              <Trash aria-hidden className="size-4" />
              {t("investments.overview.forget")}
            </Button>
          ) : (
            <>
              <p className="text-sm text-ink-2">{t("investments.overview.forgetDetail")}</p>
              {remove.isError && <div className="mt-3"><Notice tone="danger" title={describeError(remove.error)} /></div>}
              <div className="mt-4 flex flex-wrap gap-3">
                <Button variant="danger" disabled={remove.isPending} busy={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: () => setConfirming(false) })}>
                  {t("investments.overview.forgetConfirm")}
                </Button>
                <Button variant="quiet" onClick={() => setConfirming(false)}>{t("investments.overview.cancel")}</Button>
              </div>
            </>
          )}
        </div>
      )}
    </Section>
  );
}

function Funds({ data }: { readonly data: InvestmentOverview }) {
  return (
    <div className="mt-8">
      <ScrollBox label={t("investments.overview.funds")}>
        <table className="w-full text-sm">
          <thead className={stickyHead}>
            <tr className="text-left text-ink-3">
              <th scope="col" className="px-4 py-2 font-medium">{t("investments.overview.fund")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.shares")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.shareValue")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.balance")}</th>
            </tr>
          </thead>
          <tbody>
            {data.funds.map((fund) => (
              <tr key={fund.fund_id} className="border-t border-line">
                <th scope="row" className="px-4 py-3 text-left font-medium text-ink">{fund.fund} <span className="font-normal text-ink-3">{fund.series}</span></th>
                <td className="num px-4 py-3 text-right">{formatNumber(Number(fund.shares), 4)}</td>
                <td className="num px-4 py-3 text-right">{`${data.currency} ${formatNumber(Number(fund.share_value), 4)}`}</td>
                <td className="num px-4 py-3 text-right">{formatMoney(fund.value, data.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollBox>
    </div>
  );
}

function Goals({ data }: { readonly data: InvestmentOverview }) {
  const money = (value: number | null, signed = false) => (value === null ? "—" : formatMoney(value, data.currency, { signed }));
  return (
    <div className="mt-8">
      <ScrollBox label={t("investments.overview.goals")}>
        <table className="w-full text-sm">
          <thead className={stickyHead}>
            <tr className="text-left text-ink-3">
              <th scope="col" className="px-4 py-2 font-medium">{t("investments.overview.goal")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.value")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.deposited")}</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">{t("investments.overview.gain")}</th>
            </tr>
          </thead>
          <tbody>
            {data.goals.map((goal) => (
              <tr key={goal.goal_id} className="border-t border-line">
                <th scope="row" className="px-4 py-3 text-left font-medium text-ink">{goal.name.untrusted_text}</th>
                <td className="num px-4 py-3 text-right">{money(goal.value)}</td>
                <td className="num px-4 py-3 text-right">{money(goal.deposited)}</td>
                <td className="num px-4 py-3 text-right">{money(goal.gain, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollBox>
    </div>
  );
}

// ---- real-time linking: in development ------------------------------------------------------------

/** Every provider, grouped by market. Only the available ones can be chosen; the rest say when they will be. */
function ProviderSelect({ value, onChange }: { readonly value: string; readonly onChange: (id: string) => void }) {
  return (
    <div>
      <label htmlFor="investment-provider" className="mb-2 block text-sm font-medium text-ink">{t("investments.provider")}</label>
      <select id="investment-provider" value={value} className={fieldClass}
        onChange={(event) => { const chosen = PROVIDERS.find((p) => p.id === event.target.value); if (chosen?.available) onChange(chosen.id); }}>
        {PROVIDER_GROUPS.map((group) => (
          <optgroup key={group} label={t(`investments.groups.${group}`)}>
            {PROVIDERS.filter((p) => p.group === group).map((p) => (
              <option key={p.id} value={p.id} disabled={!p.available}>
                {p.available ? t(p.name) : `${t(p.name)} (${t("investments.comingSoon")})`}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

function LinkForm({ relink, live, enabled, onLinked }: { readonly relink: boolean; readonly live: boolean; readonly enabled: boolean; readonly onLinked: () => void }) {
  const link = useLinkInvestments();
  const [provider, setProvider] = useState("fintual"); // the only one available today: its fields follow
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const ready = enabled && email.trim() !== "" && password !== "" && consent;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    link.mutate({ email: email.trim(), password, consent: true }, { onSuccess: onLinked });
    setPassword(""); // sent once; never kept in the page
  }

  return (
    <div className="mt-6">
      {relink && <div className="mb-5"><Notice tone="warning" title={t("investments.link.relinkTitle")}>{t("investments.link.relinkBody")}</Notice></div>}
      {enabled ? (
        <Notice tone={live ? "warning" : "accent"} title={t(live ? "investments.liveTitle" : "investments.sandboxTitle")}>
          {t(live ? "investments.liveBody" : "investments.sandboxBody")}
        </Notice>
      ) : (
        <p className="text-xs text-ink-3">{t("investments.live.preview")}</p>
      )}
      <form onSubmit={submit} aria-label={t("investments.link.title")} className={cn("max-w-sm", enabled ? "mt-6" : "mt-3")}>
        <fieldset disabled={!enabled} className={cn("space-y-4", !enabled && "opacity-70")}>
          <ProviderSelect value={provider} onChange={setProvider} />
          <div>
            <label htmlFor="fintual-email" className="mb-2 block text-sm font-medium text-ink">{t("investments.link.email")}</label>
            <input id="fintual-email" type="email" autoComplete="off" spellCheck={false} value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
          </div>
          <div>
            <label htmlFor="fintual-password" className="mb-2 block text-sm font-medium text-ink">{t("investments.link.password")}</label>
            <input id="fintual-password" type="password" autoComplete="off" value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
          </div>
          <div className="flex items-start gap-3">
            <input id="fintual-consent" type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="mt-0.5 size-4 flex-none accent-accent" />
            <label htmlFor="fintual-consent" className="text-sm text-ink-2">{t("investments.link.consent")}</label>
          </div>
          {link.isError && <Notice tone="danger" title={linkError(link.error)} />}
          <Button type="submit" variant="primary" disabled={!ready || link.isPending} busy={link.isPending}>
            {link.isPending ? t("investments.link.submitting") : t("investments.link.submit")}
          </Button>
        </fieldset>
      </form>
    </div>
  );
}

function LinkedAccount({ account, onUnlinked }: { readonly account: AccountLink; readonly onUnlinked: () => void }) {
  const sync = useSyncInvestments();
  const unlink = useUnlinkInvestments();
  const [confirming, setConfirming] = useState(false);
  const failed = sync.isError ? sync.error : unlink.isError ? unlink.error : null;

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-base font-semibold text-ink">{t("investments.linked.title")}</h3>
        {account.synthetic && <StatusBadge tone="neutral">{t("investments.linked.synthetic")}</StatusBadge>}
      </div>
      <p className="mt-2 text-sm text-ink">{t("investments.linked.account", { email: account.email })}</p>
      <p className="mt-1 text-sm text-ink-2">
        {t("investments.linked.since", { date: formatDate(account.linked_at) })}
        {account.synced_at && <> · {t("investments.linked.synced", { date: formatDate(account.synced_at) })}</>}
      </p>
      {failed !== null && <div className="mt-4"><Notice tone="danger" title={linkError(failed)} /></div>}
      {!confirming ? (
        <div className="mt-5 flex flex-wrap gap-3">
          {!account.relink_required && (
            <Button variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending} busy={sync.isPending}>
              <ArrowsClockwise aria-hidden className="size-4" />
              {sync.isPending ? t("investments.linked.syncing") : t("investments.linked.sync")}
            </Button>
          )}
          <Button variant="quiet" onClick={() => { setConfirming(true); unlink.reset(); }}>
            <LinkBreak aria-hidden className="size-4" />
            {t("investments.linked.unlink")}
          </Button>
        </div>
      ) : (
        <div className="mt-5 max-w-prose">
          <p className="text-sm text-ink-2">{t("investments.linked.unlinkDetail")}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button variant="danger" disabled={unlink.isPending} busy={unlink.isPending}
              onClick={() => unlink.mutate(undefined, { onSuccess: () => { setConfirming(false); onUnlinked(); } })}>
              {t("investments.linked.unlinkConfirm")}
            </Button>
            <Button variant="quiet" onClick={() => setConfirming(false)}>{t("investments.linked.cancel")}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function LiveConnection() {
  const health = useHealth();
  const status = useInvestmentLink(true);
  const [unlinked, setUnlinked] = useState(false);
  const account = status.data?.link ?? null;
  // In development (ADR-044): Fintual accepts the sign-in but refuses to share the goals with a third party.
  const enabled = import.meta.env.VITE_INVESTMENT_LINKING === "on";

  return (
    <Section id="live" title={t("investments.live.title")} className="max-w-3xl"
      aside={<StatusBadge tone="warning">{t("investments.live.badge")}</StatusBadge>}>
      <p className="text-sm text-ink-2">{t("investments.live.goal")}</p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
        <li>{t("investments.live.points.upToDate")}</li>
        <li>{t("investments.live.points.providers")}</li>
        <li>{t("investments.live.points.readOnly")}</li>
      </ul>
      <div className="mt-5"><Notice tone="neutral" title={t("investments.live.statusTitle")}>{t("investments.live.status")}</Notice></div>
      {status.isPending ? <Loading className="mt-6" />
        : status.isError ? <div className="mt-6"><ErrorState error={status.error} onRetry={() => void status.refetch()} /></div>
        : (
          <>
            {unlinked && !account && <div className="mt-6"><Notice tone="positive" title={t("investments.linked.unlinked")} /></div>}
            {account && <LinkedAccount account={account} onUnlinked={() => setUnlinked(true)} />}
            {(!account || account.relink_required) && (
              <LinkForm relink={Boolean(account?.relink_required)} live={health.data?.investments === "fintual"} enabled={enabled} onLinked={() => setUnlinked(false)} />
            )}
          </>
        )}
    </Section>
  );
}

type Tab = "statements" | "live";

export function InvestmentsPage() {
  const auth = useAuth();
  const [tab, setTab] = useState<Tab>("statements");
  // A demo persona is shared by every visitor and demo mode has no sessions: neither may import or link (S31, S32).
  const own = auth.mode === "accounts" && Boolean(auth.me) && auth.me?.data_source !== "persona";

  return (
    <>
      <PageHeader title={t("investments.title")} subtitle={t("investments.description")} />
      {!own ? (
        <div className="max-w-3xl"><Notice tone="neutral" title={t("investments.readOnly")} /></div>
      ) : (
        <section aria-label={t("investments.tabs.label")}>
          <fieldset className="mb-8">
            <legend className="sr-only">{t("investments.tabs.label")}</legend>
            <div role="radiogroup" className="grid grid-cols-2 gap-1 rounded-control bg-canvas p-1 sm:inline-grid">
              {(["statements", "live"] as const).map((value) => (
                <label
                  key={value}
                  className={cn(
                    "flex cursor-pointer flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-[4px] px-3 py-1.5 text-center text-sm transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                    value === tab ? "bg-surface font-medium text-ink ring-1 ring-line" : "text-ink-2 hover:text-ink",
                  )}
                >
                  <input type="radio" name="investments-tab" value={value} checked={value === tab} onChange={() => setTab(value)} className="sr-only" />
                  {t(`investments.tabs.${value}`)}
                  {value === "live" && <>{" "}<StatusBadge tone="warning">{t("investments.live.badge")}</StatusBadge></>}
                </label>
              ))}
            </div>
          </fieldset>
          {/* The import stays mounted, so what it just read survives a look at the other tab; the real-time tab
              mounts only when opened, so nothing asks about a link that cannot be made yet. */}
          <div hidden={tab !== "statements"}>
            <ImportDocuments />
            <Portfolio />
          </div>
          {tab === "live" && <LiveConnection />}
        </section>
      )}
    </>
  );
}
