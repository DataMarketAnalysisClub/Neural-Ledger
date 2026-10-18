import { useRef, useState, type ChangeEvent } from "react";
import { ArrowLeft, Info, ShieldWarning, UploadSimple } from "@phosphor-icons/react";
import {
  useImportStatement,
  usePersona,
  useStatement,
  useStatements,
  useTransactions,
  type Statement,
  type StatementImport,
  type Statements,
  type Transactions,
} from "@/api/hooks";
import { ApiError, type Envelope } from "@/api/client";
import { useOptionalAuth } from "@/features/auth/AuthProvider";
import { RedactedText, redactedPlainText } from "@/components/redaction";
import { Button, EmptyState, ErrorState, Loading, Notice, PageHeader, ScrollBox, Section, StatusBadge, Surface, cn, describeError, stickyHead } from "@/components/ui";
import { formatDate, formatMoney, formatMonth } from "@/lib/format";
import { t, tDynamic } from "@/i18n";

/** Same limit as the API (MAX_STATEMENT_BYTES); checked here only to answer before uploading. */
const MAX_BYTES = 15 * 1024 * 1024;

type Summary = Statements[number];
type Tab = "statements" | "transactions";

/**
 * Bank statement import, the statements read back and the transaction ledger they build. Every amount is shown as the
 * API returns it. Descriptions and merchants are untrusted text with placeholders for personal data removed at import
 * (ADR-028): they render through <RedactedText>, never as markup.
 */
export function StatementsPage() {
  const { identity } = usePersona();
  return (
    <>
      <PageHeader title={t("statements.title")} subtitle={t("statements.subtitle")} />
      {/* Keyed by identity: an import result or an open statement never carries over to another persona or account. */}
      <StatementsBody key={identity.user_id} />
    </>
  );
}

function StatementsBody() {
  const auth = useOptionalAuth();
  const [tab, setTab] = useState<Tab>("statements");
  const [openId, setOpenId] = useState<string | null>(null);
  // An account without financial data has no demo scenario to fall back on; a shared demo persona is visible to all.
  const account = auth?.mode === "accounts";
  const persona = auth?.me?.data_source === "persona";
  return (
    <div className="space-y-10">
      <Notice tone="neutral" icon={Info} title={account && !persona ? t("statements.scopeAccount") : t("statements.scope")}>
        {account && persona ? t("statements.sharedPersona") : undefined}
      </Notice>
      <ImportSection />
      <section aria-label={t("statements.tabs.label")}>
        <fieldset className="mb-6">
          <legend className="sr-only">{t("statements.tabs.label")}</legend>
          <div role="radiogroup" className="inline-grid grid-cols-2 gap-1 rounded-control bg-canvas p-1">
            {(["statements", "transactions"] as const).map((value) => (
              <label
                key={value}
                className={cn(
                  "cursor-pointer rounded-[4px] px-3 py-1.5 text-sm transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                  value === tab ? "bg-surface font-medium text-ink ring-1 ring-line" : "text-ink-2 hover:text-ink",
                )}
              >
                <input type="radio" name="statements-tab" value={value} checked={value === tab} onChange={() => setTab(value)} className="sr-only" />
                {t(`statements.tabs.${value}`)}
              </label>
            ))}
          </div>
        </fieldset>
        {tab === "transactions" ? (
          <TransactionsView />
        ) : openId ? (
          <StatementDetail statementId={openId} onBack={() => setOpenId(null)} />
        ) : (
          <StatementList onOpen={setOpenId} />
        )}
      </section>
    </div>
  );
}

// ---- Import ---------------------------------------------------------------------------------------

function ImportSection() {
  const input = useRef<HTMLInputElement>(null);
  const importer = useImportStatement();
  const [fileName, setFileName] = useState<string | null>(null);
  const [tooLarge, setTooLarge] = useState(false);

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // choosing the same file again still triggers an import
    if (!file) return;
    setFileName(file.name);
    importer.reset();
    setTooLarge(file.size > MAX_BYTES);
    if (file.size <= MAX_BYTES) importer.mutate(file);
  }

  const rejectedForSize = tooLarge || (importer.error instanceof ApiError && importer.error.httpStatus === 413);

  return (
    <Section id="import" title={t("statements.upload.title")} subtitle={t("statements.upload.hint")}>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.pdf,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/png,image/jpeg"
        onChange={onFile}
        aria-label={t("statements.upload.choose")}
        className="sr-only"
        tabIndex={-1}
      />
      <Button variant="secondary" busy={importer.isPending} disabled={importer.isPending} onClick={() => input.current?.click()}>
        {!importer.isPending && <UploadSimple aria-hidden className="size-4" />}
        {t("statements.upload.choose")}
      </Button>

      <div className="mt-4 space-y-4" aria-live="polite">
        {importer.isPending && fileName && (
          <p role="status" className="text-sm text-ink-2">
            {t("statements.upload.importing", { name: fileName })}
          </p>
        )}
        {rejectedForSize && <Notice tone="danger" title={t("statements.upload.tooLarge")} />}
        {importer.isError && !rejectedForSize && (
          <Notice tone="danger" title={t("statements.upload.failed")}>
            {describeError(importer.error)}
          </Notice>
        )}
        {importer.data && fileName && <ImportResult envelope={importer.data} fileName={fileName} />}
      </div>
    </Section>
  );
}

function ImportResult({ envelope, fileName }: { envelope: Envelope<StatementImport>; fileName: string }) {
  const imports = envelope.data?.imports ?? [];
  return (
    <Surface className="p-5">
      <h3 className="text-base font-semibold text-ink">{t("statements.upload.result", { name: fileName })}</h3>
      <ul className="mt-4 divide-y divide-line">
        {imports.map((item) => (
          <li key={item.statement.statement_id} className="space-y-3 py-4 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="text-sm font-medium text-ink">
                {tDynamic("statements.banks", item.statement.bank)} <span className="num text-ink-2">{item.statement.account_ref}</span>
              </span>
              <span className="text-sm text-ink-3">{period(item.statement)}</span>
              <StatementBadges statement={item.statement} duplicate={item.duplicate} />
            </div>
            {item.duplicate && <p className="text-sm text-ink-2">{t("statements.import.duplicateDetail")}</p>}
            {item.redaction && (
              <p className="text-sm text-ink-2">
                {Object.keys(item.redaction.counts).length > 0
                  ? t("statements.import.hidden", {
                      items: Object.entries(item.redaction.counts)
                        .map(([code, n]) => `${tDynamic("redaction", code)} ×${n}`)
                        .join(", "),
                    })
                  : t("statements.import.hiddenNone")}
              </p>
            )}
            {item.redaction?.degraded && (
              <Notice tone="warning" title={t("statements.import.degraded")}>
                {t("statements.import.degradedDetail")}
              </Notice>
            )}
            {item.ledger.posted > 0 ? (
              <p className="num text-sm text-ink-2">{t("statements.import.posted", { posted: item.ledger.posted, new: item.ledger.new, uncategorized: item.ledger.uncategorized })}</p>
            ) : (
              <Notice tone="warning" title={t("statements.import.notPosted")}>
                {t("statements.import.notPostedDetail")}
              </Notice>
            )}
          </li>
        ))}
      </ul>
      {envelope.warnings.length > 0 && (
        <ul className="mt-4 space-y-1 border-t border-line pt-4 text-sm text-ink-2">
          {envelope.warnings.map((w) => (
            <li key={w.code}>
              <span className="mr-2 font-mono text-xs text-ink-3">{w.code}</span>
              {w.message}
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

function StatementBadges({ statement, duplicate = false }: { statement: Summary; duplicate?: boolean }) {
  return (
    <span className="inline-flex flex-wrap gap-2">
      {duplicate && <StatusBadge tone="neutral">{t("statements.import.duplicate")}</StatusBadge>}
      {statement.verified ? (
        <StatusBadge tone="positive">{t("statements.import.verified")}</StatusBadge>
      ) : (
        <StatusBadge tone="warning">{t("statements.import.unverified")}</StatusBadge>
      )}
      {statement.provisional && <StatusBadge tone="neutral">{t("statements.import.provisional")}</StatusBadge>}
    </span>
  );
}

function period(s: Summary): string {
  return `${formatDate(s.period_start)} – ${formatDate(s.period_end)}`;
}

// ---- Statements -----------------------------------------------------------------------------------

const th = "px-5 py-3 font-medium";

function StatementList({ onOpen }: { onOpen: (id: string) => void }) {
  const statements = useStatements();
  if (statements.isError) return <ErrorState error={statements.error} onRetry={() => void statements.refetch()} />;
  if (statements.isPending) return <Loading />;
  const rows = statements.data.data ?? [];
  if (rows.length === 0)
    return (
      <EmptyState title={t("statements.list.empty")}>
        <p>{t("statements.list.emptyDetail")}</p>
      </EmptyState>
    );
  return (
    <Surface className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <caption className="sr-only">{t("statements.list.caption")}</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th scope="col" className={th}>{t("statements.list.account")}</th>
            <th scope="col" className={th}>{t("statements.list.type")}</th>
            <th scope="col" className={th}>{t("statements.list.period")}</th>
            <th scope="col" className={cn(th, "text-right")}>{t("statements.list.closing")}</th>
            <th scope="col" className={th}>{t("statements.list.status")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.statement_id} className="border-b border-line align-top last:border-0">
              <th scope="row" className="px-5 py-3 text-left font-normal">
                <button
                  type="button"
                  onClick={() => onOpen(s.statement_id)}
                  aria-label={t("statements.list.open", { account: s.account_ref, period: period(s) })}
                  className="rounded-sm text-left text-ink underline decoration-control underline-offset-4 hover:decoration-ink"
                >
                  <span className="block font-medium">{tDynamic("statements.banks", s.bank)}</span>
                  <span className="num block text-ink-2">{s.account_ref}</span>
                </button>
              </th>
              <td className="px-5 py-3 text-ink-2">{tDynamic("statements.accountTypes", s.account_type)}</td>
              <td className="px-5 py-3 whitespace-nowrap text-ink-2">{period(s)}</td>
              <td className="num px-5 py-3 text-right whitespace-nowrap text-ink">
                {s.closing_balance === null ? "—" : formatMoney(s.closing_balance, s.currency)}
              </td>
              <td className="px-5 py-3">
                <StatementBadges statement={s} />
                {s.issues.length > 0 && <p className="mt-1.5 text-xs text-ink-3">{t("statements.list.issues", { count: s.issues.length })}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Surface>
  );
}

function StatementDetail({ statementId, onBack }: { statementId: string; onBack: () => void }) {
  const detail = useStatement(statementId);
  const back = (
    <Button variant="quiet" size="sm" onClick={onBack}>
      <ArrowLeft aria-hidden className="size-4" />
      {t("statements.detail.back")}
    </Button>
  );
  if (detail.isError)
    return (
      <div className="space-y-4">
        {back}
        <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
      </div>
    );
  if (detail.isPending) return <Loading />;
  const { statement: s, lines } = detail.data.data as Statement;
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {back}
        <h2 className="text-lg font-semibold text-ink">
          {tDynamic("statements.banks", s.bank)} <span className="num font-normal text-ink-2">{s.account_ref}</span>
        </h2>
        <span className="text-sm text-ink-3">{period(s)}</span>
        <StatementBadges statement={s} />
      </div>

      {s.issues.length > 0 && (
        <Notice tone="warning" title={t("statements.list.issues", { count: s.issues.length })}>
          <ul className="space-y-1">
            {s.issues.map((issue, i) => (
              <li key={i}>
                <span className="mr-2 font-mono text-xs">{issue.code}</span>
                {issue.message}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {s.obligations && <CardObligations obligations={s.obligations} currency={s.currency} />}

      <Section id="lines" title={t("statements.detail.lines")}>
        <Surface className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <caption className="sr-only">{t("statements.detail.caption")}</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th scope="col" className={th}>{t("statements.detail.date")}</th>
                <th scope="col" className={th}>{t("statements.detail.description")}</th>
                <th scope="col" className={th}>{t("statements.detail.kind")}</th>
                <th scope="col" className={cn(th, "text-right")}>{t("statements.detail.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.index} className="border-b border-line last:border-0">
                  <td className="px-5 py-3 whitespace-nowrap text-ink-2">{formatDate(line.posted_on)}</td>
                  <th scope="row" className="max-w-[360px] px-5 py-3 text-left font-normal text-ink">
                    <span className="line-clamp-2 break-words" title={redactedPlainText(line.description.untrusted_text)}>
                      <RedactedText text={line.description.untrusted_text} />
                    </span>
                    {line.installment && (
                      <span className="num mt-0.5 block text-xs text-ink-3">
                        {t("statements.detail.installment", { number: line.installment.number, total: line.installment.total })}
                      </span>
                    )}
                  </th>
                  <td className="px-5 py-3 text-ink-2">{line.kind ? tDynamic("statements.kinds", line.kind) : ""}</td>
                  <td className="num px-5 py-3 text-right whitespace-nowrap text-ink">{formatMoney(line.amount, s.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Surface>
        <UntrustedNote />
      </Section>
    </div>
  );
}

function CardObligations({ obligations: o, currency }: { obligations: NonNullable<Summary["obligations"]>; currency: string }) {
  const money = (v: number | null) => (v === null ? "—" : formatMoney(v, currency));
  const rows: [string, string][] = [
    [t("statements.detail.amountDue"), money(o.amount_due)],
    [t("statements.detail.minimumDue"), money(o.minimum_due)],
    [t("statements.detail.dueDate"), o.due_date ? formatDate(o.due_date) : "—"],
    [t("statements.detail.creditLimit"), money(o.credit_limit)],
    [t("statements.detail.creditUsed"), money(o.credit_used)],
    [t("statements.detail.creditAvailable"), money(o.credit_available)],
    [t("statements.detail.installmentsRemaining"), String(o.installments_remaining)],
  ];
  return (
    <Section id="card" title={t("statements.detail.card")} subtitle={t("statements.detail.asPrinted")}>
      <div className="grid gap-8 md:grid-cols-2">
        <dl className="divide-y divide-line border-y border-line text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 py-2.5">
              <dt className="text-ink-2">{label}</dt>
              <dd className="num text-right text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        {o.upcoming.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-ink">{t("statements.detail.upcoming")}</h3>
            <dl className="mt-2 divide-y divide-line border-y border-line text-sm">
              {o.upcoming.map((u) => (
                <div key={u.month} className="flex justify-between gap-4 py-2.5">
                  <dt className="text-ink-2">{formatMonth(u.month)}</dt>
                  <dd className="num text-right text-ink">{formatMoney(u.amount, currency)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </Section>
  );
}

// ---- Transactions ---------------------------------------------------------------------------------

function TransactionsView() {
  const txns = useTransactions();
  if (txns.isError) return <ErrorState error={txns.error} onRetry={() => void txns.refetch()} />;
  if (txns.isPending) return <Loading />;
  const { transactions, spending, income } = txns.data.data as Transactions;
  if (transactions.length === 0)
    return (
      <EmptyState title={t("statements.transactions.empty")}>
        <p>{t("statements.transactions.emptyDetail")}</p>
      </EmptyState>
    );
  return (
    <div className="grid gap-12 xl:grid-cols-[1fr_300px]">
      <div className="min-w-0">
        <ScrollBox label={t("statements.transactions.caption")}>
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">{t("statements.transactions.caption")}</caption>
            <thead className={stickyHead}>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th scope="col" className={th}>{t("statements.transactions.date")}</th>
                <th scope="col" className={th}>{t("statements.transactions.merchant")}</th>
                <th scope="col" className={th}>{t("statements.transactions.category")}</th>
                <th scope="col" className={th}>{t("statements.transactions.kind")}</th>
                <th scope="col" className={cn(th, "text-right")}>{t("statements.transactions.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((txn) => (
                <tr key={txn.txn_id} className="border-b border-line last:border-0">
                  <td className="px-5 py-3 whitespace-nowrap text-ink-2">{formatDate(txn.date)}</td>
                  <th scope="row" className="max-w-[320px] px-5 py-3 text-left font-normal text-ink">
                    <span className="line-clamp-2 break-words" title={redactedPlainText(txn.merchant.untrusted_text)}>
                      <RedactedText text={txn.merchant.untrusted_text} />
                    </span>
                    {txn.installment && (
                      <span className="num mt-0.5 block text-xs text-ink-3">
                        {t("statements.detail.installment", { number: txn.installment.installment_number, total: txn.installment.installment_total })}
                      </span>
                    )}
                  </th>
                  <td className="px-5 py-3 text-ink-2">{tDynamic("statements.categories", txn.category)}</td>
                  <td className="px-5 py-3 text-ink-2">{tDynamic("statements.kinds", txn.kind)}</td>
                  <td className="num px-5 py-3 text-right whitespace-nowrap text-ink">{formatMoney(txn.amount, txn.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollBox>
        <UntrustedNote />
      </div>
      <div className="space-y-10 xl:border-l xl:border-line xl:pl-10">
        <Totals id="spending" title={t("statements.transactions.spending")} totals={spending} />
        <Totals id="income" title={t("statements.transactions.income")} totals={income} />
      </div>
    </div>
  );
}

function Totals({ id, title, totals }: { id: string; title: string; totals: Transactions["spending"] }) {
  if (totals.length === 0) return null;
  return (
    <Section id={id} title={title}>
      <dl className="divide-y divide-line border-y border-line text-sm">
        {totals.map((row) => (
          <div key={`${row.currency}-${row.category}`} className="flex justify-between gap-4 py-2.5">
            <dt className="text-ink-2">
              {tDynamic("statements.categories", row.category)}
              <span className="num block text-xs text-ink-3">{t("statements.transactions.count", { count: row.count })}</span>
            </dt>
            <dd className="num text-right text-ink">{formatMoney(row.spent, row.currency)}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function UntrustedNote() {
  return (
    <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-3">
      <ShieldWarning aria-hidden className="size-4" />
      {t("copilot.untrustedNote")}
    </p>
  );
}
