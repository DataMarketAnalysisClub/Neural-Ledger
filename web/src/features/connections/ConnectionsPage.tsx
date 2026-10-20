import { useState, type FormEvent } from "react";
import { Bank, Info, LockSimple, PlugsConnected, ShieldCheck } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import {
  useAddConnection,
  useBankStart,
  useConnectBank,
  useConnectedData,
  useConnections,
  usePersona,
  useRemoveConnection,
  useSetConnectionTools,
  useSyncConnection,
  type Connection,
  type ConnectionSync,
  type Connections,
} from "@/api/hooks";
import type { Envelope } from "@/api/client";
import { Button, EmptyState, ErrorState, Loading, Notice, PageHeader, Section, StatusBadge, Surface, describeError } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { t } from "@/i18n";

const fieldClass =
  "h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";
const FINTOC_SCRIPT = "https://js.fintoc.com/v1/";

/**
 * Read-only connections (ADR-047): MCP servers of other finance apps and the user's bank. Only the user adds, chooses
 * tools, syncs and disconnects; the copilot reads what the last sync stored. Tool names, descriptions and answers are
 * the services' text: rendered as text, never as markup.
 */
export function ConnectionsPage() {
  const { identity } = usePersona();
  return (
    <>
      <PageHeader title={t("connections.title")} subtitle={t("connections.subtitle")} />
      <ConnectionsBody key={identity.user_id} />
    </>
  );
}

function ConnectionsBody() {
  const list = useConnections();
  if (list.isPending) return <Loading className="max-w-3xl" />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  const data = list.data.data;
  if (!data) return null;
  if (data.mode === "off") return <EmptyState title={t("connections.off.title")}>{t("connections.off.body")}</EmptyState>;
  const banks = data.connections.filter((c) => c.kind === "bank");
  const apps = data.connections.filter((c) => c.kind === "mcp");
  return (
    <div className="max-w-3xl space-y-10">
      <Notice tone="neutral" icon={ShieldCheck} title={t("connections.readOnly.title")}>{t("connections.readOnly.body")}</Notice>
      {data.mode === "fixture" && <Notice tone="warning" icon={Info} title={t("connections.fixture")} />}
      <Section id="bank" title={t("connections.bank.title")} subtitle={t("connections.bank.subtitle")}>
        <div className="space-y-4">
          {banks.map((c) => <ConnectionCard key={c.connection_id} connection={c} />)}
          <BankConnect bank={data.bank} />
        </div>
      </Section>
      <Section id="apps" title={t("connections.apps.title")} subtitle={t("connections.apps.subtitle")}>
        <div className="space-y-4">
          {apps.map((c) => <ConnectionCard key={c.connection_id} connection={c} />)}
          <AddApp />
        </div>
      </Section>
    </div>
  );
}

function Consent({ id, checked, onChange }: { id: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="flex items-start gap-2.5">
      <input id={id} type="checkbox" required checked={checked} onChange={(event) => onChange(event.target.checked)} className="mt-0.5 size-4 flex-none accent-accent" />
      <label htmlFor={id} className="text-sm text-ink-2">{t("connections.consent")}</label>
    </div>
  );
}

function AddApp() {
  const add = useAddConnection();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [consent, setConsent] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consent) return;
    add.mutate(
      { name, url, token: token || null },
      { onSuccess: () => { setName(""); setUrl(""); setToken(""); setConsent(false); } },
    );
  }

  return (
    <Surface className="p-5">
      <h3 className="text-base font-semibold text-ink">{t("connections.apps.add")}</h3>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <div>
          <label htmlFor="mcp-name" className="mb-1.5 block text-sm font-medium text-ink">{t("connections.apps.name")}</label>
          <input id="mcp-name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} placeholder="Racional" className={fieldClass} />
        </div>
        <div>
          <label htmlFor="mcp-url" className="mb-1.5 block text-sm font-medium text-ink">{t("connections.apps.url")}</label>
          <input id="mcp-url" type="url" required maxLength={500} inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/mcp" className={fieldClass} />
          <p className="mt-1 text-xs text-ink-3">{t("connections.apps.urlHint")}</p>
        </div>
        <div>
          <label htmlFor="mcp-token" className="mb-1.5 block text-sm font-medium text-ink">{t("connections.apps.token")}</label>
          <input id="mcp-token" type="password" autoComplete="off" maxLength={4000} value={token} onChange={(e) => setToken(e.target.value)} className={fieldClass} />
          <p className="mt-1 text-xs text-ink-3">{t("connections.apps.tokenHint")}</p>
        </div>
        <Consent id="mcp-consent" checked={consent} onChange={setConsent} />
        {add.isError && <Notice tone="danger" title={t("connections.apps.failed")}>{describeError(add.error)}</Notice>}
        <Button type="submit" variant="primary" busy={add.isPending} disabled={add.isPending || !consent}>
          <PlugsConnected aria-hidden className="size-4" />
          {t("connections.apps.submit")}
        </Button>
      </form>
    </Surface>
  );
}

interface FintocWidget { open: () => void }
interface FintocGlobal {
  create: (options: { publicKey: string; widgetToken: string; onSuccess: (intent: { exchangeToken: string }) => void; onExit?: () => void }) => FintocWidget;
}

function loadFintoc(): Promise<FintocGlobal> {
  const existing = (window as unknown as { Fintoc?: FintocGlobal }).Fintoc;
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = FINTOC_SCRIPT;
    script.onload = () => {
      const loaded = (window as unknown as { Fintoc?: FintocGlobal }).Fintoc;
      if (loaded) resolve(loaded);
      else reject(new Error("fintoc"));
    };
    script.onerror = () => reject(new Error("fintoc"));
    document.head.appendChild(script);
  });
}

function BankConnect({ bank }: { bank: Connections["bank"] }) {
  const start = useBankStart();
  const connect = useConnectBank();
  const [consent, setConsent] = useState(false);
  const [widgetError, setWidgetError] = useState(false);
  if (bank.aggregator === "none") return <p className="text-sm text-ink-3">{t("connections.bank.unavailable")}</p>;

  async function open() {
    setWidgetError(false);
    const started = await start.mutateAsync().catch(() => null);
    const info = started?.data;
    if (!info) return;
    if (!info.widget_token || !info.public_key) {
      connect.mutate("fixture"); // synthetic bank: no widget to open
      return;
    }
    try {
      const fintoc = await loadFintoc();
      fintoc.create({ publicKey: info.public_key, widgetToken: info.widget_token, onSuccess: (intent) => connect.mutate(intent.exchangeToken) }).open();
    } catch {
      setWidgetError(true);
    }
  }

  const busy = start.isPending || connect.isPending;
  return (
    <Surface className="p-5">
      <div className="space-y-4">
        <Consent id="bank-consent" checked={consent} onChange={setConsent} />
        {(start.isError || connect.isError) && <Notice tone="danger" title={t("connections.bank.failed")}>{describeError(start.error ?? connect.error)}</Notice>}
        {widgetError && <Notice tone="danger" title={t("connections.bank.widgetFailed")} />}
        <Button variant="primary" busy={busy} disabled={busy || !consent} onClick={() => void open()}>
          <Bank aria-hidden className="size-4" />
          {t("connections.bank.connect", { aggregator: bank.aggregator })}
        </Button>
      </div>
    </Surface>
  );
}

function ConnectionCard({ connection }: { connection: Connection }) {
  const sync = useSyncConnection();
  const remove = useRemoveConnection();
  const synced = connection.last_synced_at ? t("connections.syncedOn", { date: formatDate(connection.last_synced_at) }) : t("connections.neverSynced");
  return (
    <Surface className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-ink">{connection.name}</h3>
          <p className="mt-0.5 text-sm text-ink-3">{connection.host} · {synced}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" busy={sync.isPending} disabled={sync.isPending} onClick={() => sync.mutate(connection.connection_id)}>
            {t("connections.sync")}
          </Button>
          <Button variant="quiet" size="sm" busy={remove.isPending} disabled={remove.isPending} onClick={() => remove.mutate(connection.connection_id)}>
            {t("connections.remove")}
          </Button>
        </div>
      </div>
      <div aria-live="polite">
        {sync.isError && <div className="mt-4"><Notice tone="danger" title={t("connections.syncFailed")}>{describeError(sync.error)}</Notice></div>}
        {remove.isError && <div className="mt-4"><Notice tone="danger" title={describeError(remove.error)} /></div>}
        {sync.data && <SyncResult envelope={sync.data} />}
      </div>
      {connection.kind === "mcp" && <ToolPicker key={connection.tools.map((tool) => `${tool.name}:${tool.enabled}`).join("|")} connection={connection} />}
      {connection.kind === "mcp" && connection.last_synced_at && <LastAnswers connectionId={connection.connection_id} />}
    </Surface>
  );
}

function SyncResult({ envelope }: { envelope: Envelope<ConnectionSync> }) {
  const data = envelope.data;
  if (!data) return null;
  if (data.statements) {
    const unverified = data.statements.imports.some((i) => !i.statement.verified);
    return (
      <div className="mt-4">
        <Notice tone={unverified ? "warning" : "positive"} title={t("connections.bank.imported", { count: data.statements.imports.length })}>
          {unverified ? t("connections.bank.unverified") : undefined}{" "}
          <Link to="/statements" className="font-medium text-accent underline">{t("connections.bank.see")}</Link>
        </Notice>
      </div>
    );
  }
  if (data.connection.kind === "bank") return <p className="mt-4 text-sm text-ink-2">{t("connections.bank.nothingNew")}</p>;
  const failed = data.results.filter((r) => !r.ok);
  return (
    <p className="mt-4 text-sm text-ink-2">
      {data.results.length === 0 ? t("connections.noToolsEnabled") : t("connections.syncedTools", { ok: data.results.length - failed.length, total: data.results.length })}
    </p>
  );
}

function ToolPicker({ connection }: { connection: Connection }) {
  const save = useSetConnectionTools();
  const [enabled, setEnabled] = useState(() => new Set(connection.tools.filter((tool) => tool.enabled).map((tool) => tool.name)));
  const changed = connection.tools.some((tool) => tool.enabled !== enabled.has(tool.name));
  function toggle(name: string, on: boolean) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  }
  return (
    <fieldset className="mt-5 border-t border-line pt-4">
      <legend className="text-sm font-medium text-ink">{t("connections.tools.title")}</legend>
      {connection.tools.length === 0 && <p className="mt-2 text-sm text-ink-3">{t("connections.tools.none")}</p>}
      <ul className="mt-3 space-y-3">
        {connection.tools.map((tool) => {
          const id = `tool-${connection.connection_id}-${tool.name}`;
          return (
            <li key={tool.name} className="flex items-start gap-2.5">
              <input
                id={id}
                type="checkbox"
                disabled={tool.blocked !== null}
                checked={enabled.has(tool.name)}
                onChange={(event) => toggle(tool.name, event.target.checked)}
                aria-describedby={`${id}-about`}
                className="mt-0.5 size-4 flex-none accent-accent disabled:opacity-40"
              />
              <div className="min-w-0">
                <label htmlFor={id} className="font-mono text-sm break-all text-ink">{tool.name}</label>
                <p id={`${id}-about`} className="text-xs text-ink-3">
                  {tool.blocked ? (
                    <StatusBadge tone="danger" icon={LockSimple}>{t(`connections.tools.blocked.${tool.blocked}`)}</StatusBadge>
                  ) : (
                    tool.description.untrusted_text || t("connections.tools.noDescription")
                  )}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
      {save.isError && <div className="mt-3"><Notice tone="danger" title={describeError(save.error)} /></div>}
      {changed && (
        <Button className="mt-4" variant="secondary" size="sm" busy={save.isPending} disabled={save.isPending} onClick={() => save.mutate({ id: connection.connection_id, enabled: [...enabled] })}>
          {t("connections.tools.save")}
        </Button>
      )}
    </fieldset>
  );
}

function LastAnswers({ connectionId }: { connectionId: string }) {
  const data = useConnectedData();
  const source = data.data?.data?.connections.find((c) => c.connection_id === connectionId);
  if (!source || source.results.length === 0) return null;
  return (
    <details className="mt-5 border-t border-line pt-4">
      <summary className="cursor-pointer text-sm font-medium text-ink">{t("connections.answers")}</summary>
      <p className="mt-2 text-xs text-ink-3">{t("connections.answersHint")}</p>
      {source.results.map((r) => (
        <div key={r.tool} className="mt-3">
          <p className="font-mono text-xs text-ink-2">{r.tool}{r.ok ? "" : ` · ${t("connections.failedTool")}`}</p>
          {r.ok && <pre className="mt-1 max-h-48 overflow-auto rounded-control bg-canvas p-3 text-xs break-all whitespace-pre-wrap text-ink">{r.content.untrusted_text}</pre>}
        </div>
      ))}
    </details>
  );
}
