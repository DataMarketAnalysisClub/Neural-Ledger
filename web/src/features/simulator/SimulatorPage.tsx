import { cloneElement, useId, useRef, useState, type FormEvent, type ReactElement } from "react";
import { ArrowRight, CheckCircle, Prohibit, Warning, WarningOctagon } from "@phosphor-icons/react";
import { useFinancialState, useSimulatePurchase, type IncludePlan, type PurchaseInput, type PurchaseSimulation } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { HeadroomDumbbell } from "@/components/charts";
import { Button, EmptyState, ErrorState, Notice, PageHeader, Section, Surface, cn, describeError, type Tone } from "@/components/ui";
import { formatMoney, formatMonth, formatPercent } from "@/lib/format";
import { t, tDynamic } from "@/i18n";


interface FormState {
  note: string;
  amount: string;
  installments: string;
  firstMonth: string;
  rate: string;
  plan: IncludePlan;
}

const EMPTY: FormState = { note: "", amount: "", installments: "12", firstMonth: "", rate: "", plan: "none" };

function verdictTone(verdict: PurchaseSimulation["verdict"]): Tone {
  if (verdict === "FITS_ALL") return "positive";
  if (verdict === "FITS_TYPICAL_ONLY") return "warning";
  return "danger";
}

export function SimulatorPage() {
  const state = useFinancialState();
  const simulate = useSimulatePurchase();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [clientError, setClientError] = useState<{ field: keyof FormState; message: string } | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const ids = { amount: useId(), installments: useId(), first: useId(), rate: useId(), plan: useId(), note: useId() };
  const currency = state.data?.data?.currency ?? "CLP";
  const monthOptions = monthsFrom(state.data?.data?.first_cycle, 12);

  // The server is the authority on validity; this only catches empty or non-numeric input early.
  const serverField = simulate.error instanceof ApiError ? simulate.error.detail.field : null;
  const fieldError = (name: keyof FormState, apiName: string) =>
    clientError?.field === name ? clientError.message : serverField === apiName ? describeError(simulate.error) : null;

  function run(next: FormState) {
    setClientError(null);
    const amount = Number(next.amount.replace(/[,\s]/g, ""));
    if (!next.amount || !Number.isInteger(amount)) {
      setClientError({ field: "amount", message: t("simulator.form.amountHint", { currency }) });
      return;
    }
    const input: PurchaseInput = { amount, installments: Number(next.installments), include_plan: next.plan };
    if (next.firstMonth) input.first_installment_month = next.firstMonth;
    if (next.rate.trim()) input.monthly_rate = Number(next.rate) / 100; // the user types a percentage
    simulate.mutate(input, { onSuccess: () => resultRef.current?.focus() });
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    run(form);
  }

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const result = simulate.data?.data;
  const envelope = simulate.data;

  return (
    <>
      <PageHeader title={t("simulator.title")} subtitle={t("simulator.subtitle")} />

      <div className="grid gap-12 lg:grid-cols-[340px_1fr]">
        <Section id="purchase-form" title={t("simulator.form.title")}>
          <form onSubmit={onSubmit} noValidate className="space-y-5">
            <Field id={ids.amount} label={`${t("simulator.form.amount")} (${currency})`} hint={t("simulator.form.amountHint", { currency })} error={fieldError("amount", "amount")}>
              <input
                id={ids.amount}
                inputMode="numeric"
                autoComplete="off"
                value={form.amount}
                onChange={(e) => update("amount", e.target.value)}
                placeholder="400000"
                className="num"
              />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field
                id={ids.installments}
                label={t("simulator.form.installments")}
                hint={t("simulator.form.installmentsHint")}
                error={fieldError("installments", "installments")}
              >
                {/* The API decides what is valid (fc-0.2: 1 to 48); min and max only guide the browser control. */}
                <input
                  id={ids.installments}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={48}
                  step={1}
                  value={form.installments}
                  onChange={(e) => update("installments", e.target.value)}
                  className="num"
                />
              </Field>
              <Field id={ids.first} label={t("simulator.form.firstMonth")} hint={t("simulator.form.firstMonthHint")} error={fieldError("firstMonth", "first_installment_month")}>
                <select id={ids.first} value={form.firstMonth} onChange={(e) => update("firstMonth", e.target.value)}>
                  <option value="">{t("simulator.form.firstMonthDefault")}</option>
                  {monthOptions.map((m) => (
                    <option key={m} value={m}>
                      {formatMonth(m)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field id={ids.rate} label={t("simulator.form.rate")} hint={t("simulator.form.rateHint")} error={fieldError("rate", "monthly_rate")}>
              <input id={ids.rate} inputMode="decimal" value={form.rate} onChange={(e) => update("rate", e.target.value)} placeholder="2.5" className="num" />
            </Field>
            <Field id={ids.plan} label={t("simulator.form.plan")} error={fieldError("plan", "include_plan")}>
              <select id={ids.plan} value={form.plan} onChange={(e) => update("plan", e.target.value as IncludePlan)}>
                {(["none", "recommended", "active"] as const).map((p) => (
                  <option key={p} value={p}>
                    {t(`simulator.form.planOptions.${p}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field id={ids.note} label={t("simulator.form.note")} hint={t("simulator.form.noteHint")}>
              <input id={ids.note} value={form.note} onChange={(e) => update("note", e.target.value)} placeholder="Laptop" />
            </Field>
            <Button type="submit" variant="primary" size="lg" className="w-full" busy={simulate.isPending} disabled={simulate.isPending}>
              {simulate.isPending ? t("simulator.form.submitting") : t("simulator.form.submit")}
            </Button>
          </form>
        </Section>

        <div ref={resultRef} tabIndex={-1} className="min-w-0 outline-none" aria-live="polite">
          {simulate.isError && !serverField && <ErrorState error={simulate.error} />}
          {!result && !simulate.isError && <EmptyState title={t("simulator.empty")} />}
          {result && envelope && (
            <div className="space-y-10">
              {(() => {
                const limiting = result.impacts.find((i) => i.scenario === "conservative") ?? result.impacts[0];
                return (
                  <h2 className="text-xl font-semibold text-ink">
                    {result.verdict === "FITS_ALL" || !limiting
                      ? t("simulator.headline.fits")
                      : t("simulator.headline.limits", { month: formatMonth(limiting.binding_month_after, "long") })}
                  </h2>
                );
              })()}
              <Notice
                tone={verdictTone(result.verdict)}
                icon={result.verdict === "FITS_ALL" ? CheckCircle : result.verdict === "FITS_TYPICAL_ONLY" ? Warning : result.verdict === "BASELINE_BREACH" ? Prohibit : WarningOctagon}
                title={<span className="text-base">{tDynamic("simulator.verdict", result.verdict)}</span>}
              >
                {tDynamic("simulator.verdictBody", result.verdict)}
              </Notice>

              {/* The quote as one line of engine facts, not a row of equal tiles. */}
              <p className="num max-w-prose text-base leading-relaxed text-ink-2">
                <strong className="font-semibold text-ink">{formatMoney(result.quote.installment, currency)}</strong>{" "}
                {t("simulator.quote.line1", { count: result.quote.installments, month: formatMonth(result.first_installment_month) })}{" "}
                <strong className="font-semibold text-ink">{formatMoney(result.quote.total_cost, currency)}</strong>{" "}
                {t("simulator.quote.line2", { interest: formatMoney(result.quote.total_interest, currency) })}{" "}
                <strong className="font-semibold text-ink">{formatPercent(result.quote.effective_annual_rate)}</strong>{" "}
                {t("simulator.quote.line3", { rate: formatPercent(result.quote.monthly_rate) })}
              </p>

              {envelope.warnings.length > 0 && (
                <Section id="assumptions" title={t("warnings.title")}>
                  <ul className="space-y-2">
                    {envelope.warnings.map((w) => (
                      <li key={w.code} className="flex gap-2 text-sm text-ink-2">
                        <Warning aria-hidden weight="bold" className="mt-0.5 size-4 shrink-0 text-warning" />
                        {w.message}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <Surface className="p-6">
                <HeadroomDumbbell
                  currency={currency}
                  rows={result.impacts.map((i) => ({
                    scenario: i.scenario,
                    before: i.lowest_headroom_before,
                    after: i.lowest_headroom_after,
                    month: i.binding_month_after,
                  }))}
                />
              </Surface>

              <Section id="alternatives" title={t("simulator.alternatives.title")} subtitle={t("simulator.alternatives.subtitle")}>
                {result.alternatives.length === 0 ? (
                  <p className="text-sm text-ink-2">{t("simulator.alternatives.none")}</p>
                ) : (
                  <ul className="divide-y divide-line border-y border-line">
                    {result.alternatives.map((a) => (
                      <li key={`${a.kind}-${a.amount}-${a.installments}-${a.first_installment_month}`} className="flex flex-wrap items-center justify-between gap-4 py-4">
                        <div>
                          <p className="font-medium text-ink">
                            {a.kind === "defer_start"
                              ? t("simulator.alternatives.defer_start", { month: formatMonth(a.first_installment_month, "long") })
                              : a.kind === "change_installments"
                                ? t("simulator.alternatives.change_installments", { count: a.installments })
                                : t("simulator.alternatives.reduce_amount", { amount: formatMoney(a.amount, currency) })}
                          </p>
                          <p className="num mt-0.5 text-sm text-ink-2">
                            {t("simulator.alternatives.detail", { installment: formatMoney(a.installment, currency), total: formatMoney(a.total_cost, currency) })}
                          </p>
                        </div>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            const next = { ...form, amount: String(a.amount), installments: String(a.installments), firstMonth: a.first_installment_month };
                            setForm(next);
                            run(next);
                          }}
                        >
                          {t("simulator.alternatives.load")}
                          <ArrowRight aria-hidden className="size-4" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/** Label above, control, hint, and error below; the control gets aria-describedby and aria-invalid. */
export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactElement<{ className?: string }>;
}) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint && !error ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  const control = cloneElement(children, {
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
    className: cn(
      "h-10 w-full rounded-control border bg-surface px-3 text-sm text-ink placeholder:text-ink-3",
      "transition-[border-color,box-shadow] duration-150 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25",
      error ? "border-danger" : "border-control",
      children.props.className,
    ),
  } as Record<string, unknown>);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">
        {label}
      </label>
      {control}
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-xs text-ink-3">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-danger">
          <WarningOctagon aria-hidden weight="bold" className="size-3.5" />
          {error}
        </p>
      )}
    </div>
  );
}

/** Month options ("YYYY-MM") starting at the first projected cycle. Calendar arithmetic only. */
function monthsFrom(start: string | undefined, count: number): string[] {
  if (!start) return [];
  const [y, m] = start.split("-").map(Number);
  if (!y || !m) return [];
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(Date.UTC(y, m - 1 + i, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}
