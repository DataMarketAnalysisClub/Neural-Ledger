import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  CalendarDots,
  ChartLineDown,
  ChatText,
  Files,
  LinkSimple,
  PiggyBank,
  Receipt,
  UserCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useFinancialState, useHealth, usePersona } from "@/api/hooks";
import type { PersonaId } from "@/api/client";
import { t, type MessageKey } from "@/i18n";
import { formatDate } from "@/lib/format";
import { Button, ErrorState, Notice, StatusBadge, cn } from "@/components/ui";
import { features } from "@/lib/features";
import { useAuth } from "@/features/auth/AuthProvider";

interface NavItem {
  to: string;
  label: MessageKey;
  icon: Icon;
  hidden?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "nav.overview", icon: ChartLineDown },
  { to: "/commitments", label: "nav.commitments", icon: CalendarDots },
  { to: "/simulator", label: "nav.simulator", icon: Receipt },
  { to: "/plan", label: "nav.plan", icon: PiggyBank },
  { to: "/copilot", label: "nav.copilot", icon: ChatText },
  { to: "/audit", label: "nav.audit", icon: LinkSimple },
  { to: "/statements", label: "nav.statements", icon: Files, hidden: !features.statements },
  { to: "/profile", label: "auth.account", icon: UserCircle },
];

/** The product mark: a balance stepping down to a protected floor, the product's own mechanism. */
function Mark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-6 shrink-0">
      <rect x="2" y="3" width="5" height="18" rx="1.5" fill="var(--text)" />
      <rect x="9.5" y="8" width="5" height="13" rx="1.5" fill="var(--text)" opacity="0.55" />
      <rect x="17" y="14" width="5" height="7" rx="1.5" fill="var(--accent)" />
    </svg>
  );
}

function PersonaSwitcher() {
  const { persona, setPersona } = usePersona();
  const options: PersonaId[] = ["camila", "diego"];
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs font-medium text-ink-3">{t("app.viewingAs")}</legend>
      <div className="grid grid-cols-2 gap-1 rounded-control bg-canvas p-1" role="radiogroup">
        {options.map((id) => {
          const selected = id === persona;
          return (
            <label
              key={id}
              className={cn(
                "flex cursor-pointer flex-col rounded-[4px] px-2.5 py-1.5 transition-colors duration-150",
                selected ? "bg-surface text-ink ring-1 ring-line" : "text-ink-2 hover:text-ink",
              )}
            >
              <input type="radio" name="persona" value={id} checked={selected} onChange={() => setPersona(id)} className="sr-only" />
              <span className="text-sm font-medium">{t(`personas.${id}.name`)}</span>
              <span className="text-xs text-ink-3">{t(`personas.${id}.detail`)}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function RuleCounter() {
  const state = useFinancialState();
  const count = state.data?.data?.active_rules;
  if (count === undefined) return null;
  return <p className="num text-xs text-ink-3">{t("nav.rules", { count })}</p>;
}

function DataAsOf() {
  const state = useFinancialState();
  const asOf = state.data?.as_of;
  return asOf ? <span>{t("app.asOf", { date: formatDate(asOf) })}</span> : null;
}

function SandboxSeal({ showData }: { readonly showData: boolean }) {
  const health = useHealth();
  const mode = health.data?.mode;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 font-medium text-ink-2">
        <span aria-hidden className="size-1.5 rounded-full bg-positive" />
        {t("app.sandbox")}
      </span>
      {mode && (
        <span title={health.data ? t("app.modeDetail", { model: health.data.language_model }) : undefined}>
          {mode === "live" ? t("app.modeLive") : t("app.modeOffline")}
        </span>
      )}
      {showData && <DataAsOf />}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const signout = useMutation({ mutationFn: auth.signout });
  const isAccount = auth.mode === "accounts";
  const isMock = import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true";
  const showData = !isAccount || (!isMock && (auth.me?.data_source === "sample" || auth.me?.data_source === "persona"));
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        {t("app.skipToContent")}
      </a>

      <aside className="border-b border-line bg-rail lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:border-r lg:border-b-0">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
          <Mark />
          <span className="text-base font-semibold tracking-[-0.01em] text-ink">{t("app.name")}</span>
        </div>
        {!isAccount && <div className="px-4 pb-4"><PersonaSwitcher /></div>}
        <nav aria-label={t("nav.label")} className="px-3 pb-3 lg:flex-1 lg:overflow-y-auto">
          {/* Below lg every item stays visible in a grid; nothing hides off-screen. */}
          <ul className={cn("grid grid-cols-3 gap-1 lg:flex lg:flex-col", isAccount ? "sm:grid-cols-4" : "sm:grid-cols-6")}>
            {NAV.filter((item) => !item.hidden && (isAccount || item.to !== "/profile")).map(({ to, label, icon: IconCmp }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-11 flex-col items-center justify-center gap-1 rounded-control px-1.5 py-1.5 text-center text-xs leading-tight transition-colors duration-150 lg:h-10 lg:min-h-0 lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:py-0 lg:text-left lg:text-sm lg:whitespace-nowrap",
                      isActive ? "bg-surface font-medium text-ink ring-1 ring-line" : "text-ink-2 hover:bg-surface/60 hover:text-ink",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <IconCmp aria-hidden weight={isActive ? "fill" : "regular"} className={cn("size-[18px] shrink-0", isActive && "text-accent")} />
                      {t(label)}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        {showData && <div className="hidden border-t border-line px-5 py-4 lg:block"><RuleCounter /></div>}
      </aside>

      <div className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-3 lg:px-10">
          <SandboxSeal showData={showData} />
          {isAccount && <div className="flex flex-wrap items-center gap-3 text-sm">
            {isMock && <StatusBadge tone="warning">{t("auth.mock")}</StatusBadge>}
            <Button asChild variant="quiet" size="sm"><Link to="/profile">{t("auth.account")}</Link></Button>
            <Button variant="quiet" size="sm" onClick={() => signout.mutate()} disabled={signout.isPending} busy={signout.isPending}>
              {signout.isPending ? t("auth.signingOut") : t("auth.signout")}
            </Button>
          </div>}
        </div>
        {signout.isError && <div className="px-6 pt-4 lg:px-10"><ErrorState error={signout.error} /></div>}
        {isAccount && auth.me?.data_source === "sample" && <div className="border-b border-line px-6 py-3 lg:px-10">
          <Notice tone="warning" title={t("profile.sampleBanner")} />
        </div>}
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1280px] flex-1 px-6 py-8 outline-none lg:px-10 lg:py-10">
          {children}
        </main>
        <footer className="px-6 pb-6 text-xs text-ink-3 lg:px-10">{t(isAccount ? "auth.footer" : "app.footer")}</footer>
      </div>
    </div>
  );
}
