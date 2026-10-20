import { useState, type FormEvent } from "react";
import { DownloadSimple, Trash } from "@phosphor-icons/react";
import {
  useDeclareIncome,
  useDeleteMemoryChain,
  useMemory,
  useMemoryExport,
  useSetMemoryConsent,
  type MemoryView,
} from "@/api/hooks";
import { Button, ErrorState, Loading, Notice, Section, StatusBadge } from "@/components/ui";
import { t } from "@/i18n";
import { formatMoney, formatMonth } from "@/lib/format";
import { memoryProblem, parseAmount } from "./memoryText";

type Item = MemoryView["items"][number];
type Declaration = NonNullable<Item["current"]>;

const fieldClass = "mt-1 block h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink";

/**
 * "What Neural Ledger knows about you" (ADR-048): the memory consent, the declared salary with what the statements
 * say about it, a new version, the export and the deletion. The user's own data stays readable, exportable and
 * deletable without consent; changing it needs consent. Saved only: nothing here changes a projection. A limited
 * administration of memory, not the whole of the G02/G06 data rights.
 */
export function MemorySection({ persona }: { readonly persona: boolean }) {
  const memory = useMemory(!persona);
  if (persona) {
    return (
      <Section id="memory" title={t("profile.memory.title")} className="mt-10 max-w-3xl border-t border-line pt-10">
        <p className="text-sm text-ink-2">{t("profile.memory.persona")}</p>
      </Section>
    );
  }
  return (
    <Section id="memory" title={t("profile.memory.title")} className="mt-10 max-w-3xl border-t border-line pt-10">
      <p className="max-w-prose text-sm text-ink-2">{t("profile.memory.description")}</p>
      {memory.isPending ? <Loading className="mt-4 max-w-xs" /> : memory.isError ? (
        <ErrorState error={memory.error} onRetry={() => void memory.refetch()} />
      ) : (
        <MemoryAdmin view={memory.data} />
      )}
    </Section>
  );
}

function MemoryAdmin({ view }: { readonly view: MemoryView }) {
  const granted = view.consent === "granted";
  const item = view.items[0];
  // Kept here: a write re-reads the view, which remounts the form that made it, and the result must outlive that.
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <>
      <ConsentToggle consent={view.consent} />
      {notice && <div role="status" className="mt-4"><Notice tone="positive" title={notice} /></div>}
      {item ? <Salary item={item} granted={granted} /> : <p className="mt-6 text-sm text-ink-2">{t("profile.memory.none")}</p>}
      {granted && <Declare key={`${item?.chain_id ?? "none"}-${item?.versions ?? 0}`} item={item} onSaved={() => setNotice(t("profile.memory.saved"))} />}
      <div className="mt-6 flex flex-wrap gap-3">
        <Export />
        {item && <Delete key={item.chain_id} chainId={item.chain_id} onDeleted={(count) => setNotice(t("profile.memory.deleted", { count }))} />}
      </div>
    </>
  );
}

function ConsentToggle({ consent }: { readonly consent: MemoryView["consent"] }) {
  const set = useSetMemoryConsent();
  const granted = consent === "granted";
  return (
    <div className="mt-5 rounded-control border border-line p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-ink">
        <StatusBadge tone={granted ? "positive" : "neutral"}>
          {t(granted ? "profile.memory.consentOn" : consent === "revoked" ? "profile.memory.consentOff" : "profile.memory.consentMissing")}
        </StatusBadge>
      </p>
      <p className="mt-2 max-w-prose text-sm text-ink-2">{t(granted ? "profile.memory.consentOnDetail" : "profile.memory.consentOffDetail")}</p>
      {set.isError && <div className="mt-3"><ErrorState error={set.error} /></div>}
      <Button variant="secondary" size="sm" className="mt-3" busy={set.isPending} disabled={set.isPending} onClick={() => set.mutate(granted ? "revoked" : "granted")}>
        {t(granted ? "profile.memory.revoke" : "profile.memory.grant")}
      </Button>
    </div>
  );
}

function Salary({ item, granted }: { readonly item: Item; readonly granted: boolean }) {
  const shown: Declaration | null = item.current ?? item.upcoming;
  if (!shown) return null;
  const value = shown.value.salary_net;
  const status = !granted || !item.check ? "off" : item.check.status;
  return (
    <div className="mt-6">
      <p className="text-xs font-medium text-ink-3">{t("profile.memory.salary")}</p>
      <p className="mt-1 text-xl font-semibold text-ink">{formatMoney(value.amount, "CLP")}</p>
      <p className="text-sm text-ink-2">{t("profile.memory.since", { month: formatMonth(value.effective_from, "long") })}</p>
      {item.current && item.upcoming && (
        <p className="text-sm text-ink-2">
          {t("profile.memory.upcoming", { month: formatMonth(item.upcoming.value.salary_net.effective_from, "long"), amount: formatMoney(item.upcoming.value.salary_net.amount, "CLP") })}
        </p>
      )}
      <p className="mt-2 text-sm text-ink-2">{t(`profile.memory.status.${status}`)}</p>
      <p className="mt-1 font-mono text-xs text-ink-3">{t("profile.memory.versions", { count: item.versions })}</p>
    </div>
  );
}

/** A new version (or the first declaration): the head version is the chain's version count (they start at 1). */
function Declare({ item, onSaved }: { readonly item: Item | undefined; readonly onSaved: () => void }) {
  const declare = useDeclareIncome();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [month, setMonth] = useState("");
  const parsed = parseAmount(amount);
  const ready = parsed !== null && /^\d{4}-\d{2}$/.test(month);
  const problem = declare.isError ? memoryProblem(declare.error) : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || declare.isPending) return;
    declare.mutate({ salary_net: { amount: parsed, net: true, effective_from: month }, expected_version: item?.versions ?? 0 }, { onSuccess: onSaved });
  }

  if (!open) {
    return (
      <Button variant="secondary" size="sm" className="mt-4" onClick={() => setOpen(true)}>
        {t(item ? "profile.memory.edit" : "profile.memory.declare")}
      </Button>
    );
  }
  return (
    <form onSubmit={submit} aria-label={t(item ? "profile.memory.edit" : "profile.memory.declare")} className="mt-4 grid max-w-md gap-3 sm:grid-cols-2">
      <label className="text-sm text-ink-2">
        {t("profile.memory.amount")}
        <input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} className={fieldClass} />
      </label>
      <label className="text-sm text-ink-2">
        {t("profile.memory.month")}
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className={fieldClass} />
      </label>
      {problem === "consent" && <div className="sm:col-span-2"><Notice tone="warning" title={t("profile.memory.consentRequired")} /></div>}
      {problem === "conflict" && <div className="sm:col-span-2"><Notice tone="warning" title={t("profile.memory.conflict")} /></div>}
      {(problem === "invalid" || problem === "other") && <div className="sm:col-span-2"><ErrorState error={declare.error} /></div>}
      <p className="text-xs text-ink-3 sm:col-span-2">{t("copilot.memory.savedOnly")}</p>
      <div className="flex flex-wrap gap-3 sm:col-span-2">
        <Button type="submit" size="sm" variant="primary" disabled={!ready || declare.isPending} busy={declare.isPending}>{t("profile.memory.save")}</Button>
        <Button type="button" size="sm" variant="quiet" onClick={() => setOpen(false)}>{t("profile.memory.cancel")}</Button>
      </div>
    </form>
  );
}

function Export() {
  const exported = useMemoryExport();
  return (
    <div>
      <Button
        variant="secondary"
        size="sm"
        busy={exported.isPending}
        onClick={() =>
          exported.mutate(undefined, {
            onSuccess: (data) => {
              // A download of the user's own data, as JSON; nothing in it is rendered as markup.
              const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
              const link = document.createElement("a");
              link.href = url;
              link.download = "neural-ledger-memory.json";
              link.click();
              URL.revokeObjectURL(url);
            },
          })
        }
      >
        <DownloadSimple aria-hidden className="size-4" />
        {t("profile.memory.export")}
      </Button>
      {exported.isSuccess && <p role="status" className="mt-2 text-xs text-ink-2">{t("profile.memory.exported", { count: exported.data.declarations.length })}</p>}
      {exported.isError && <ErrorState error={exported.error} />}
    </div>
  );
}

function Delete({ chainId, onDeleted }: { readonly chainId: string; readonly onDeleted: (count: number) => void }) {
  const remove = useDeleteMemoryChain();
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        <Trash aria-hidden className="size-4" />
        {t("profile.memory.delete")}
      </Button>
    );
  }
  return (
    <div className="max-w-md">
      <p className="text-sm text-ink-2">{t("profile.memory.deleteDetail")}</p>
      {remove.isError && <ErrorState error={remove.error} />}
      <div className="mt-3 flex flex-wrap gap-3">
        <Button variant="danger" size="sm" busy={remove.isPending} disabled={remove.isPending} onClick={() => remove.mutate(chainId, { onSuccess: (result) => onDeleted(result.deleted_versions) })}>{t("profile.memory.deleteConfirm")}</Button>
        <Button variant="quiet" size="sm" onClick={() => setOpen(false)}>{t("profile.memory.cancel")}</Button>
      </div>
    </div>
  );
}
