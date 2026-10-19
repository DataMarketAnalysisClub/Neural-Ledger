import { useEffect, useRef, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  CalendarDots,
  ChartLineDown,
  Files,
  LinkSimple,
  PiggyBank,
  Receipt,
  UserCircle,
} from "@phosphor-icons/react";
import { CopilotGlyph, type NavIcon } from "@/components/CopilotGlyph";
import { useFinancialState, useHealth, usePersona } from "@/api/hooks";
import type { PersonaId } from "@/api/client";
import { t, type MessageKey } from "@/i18n";
import { formatDate } from "@/lib/format";
import { Button, ErrorState, StatusBadge, cn } from "@/components/ui";
import { useAuth } from "@/features/auth/AuthProvider";
import { MobileBar, ProfileLink } from "./MobileNav";
import { useMarkLanded } from "./mobileLanding";

interface NavItem {
  to: string;
  label: MessageKey;
  icon: NavIcon;
}

const NAV: NavItem[] = [
  { to: "/", label: "nav.overview", icon: ChartLineDown },
  { to: "/commitments", label: "nav.commitments", icon: CalendarDots },
  { to: "/simulator", label: "nav.simulator", icon: Receipt },
  { to: "/plan", label: "nav.plan", icon: PiggyBank },
  { to: "/copilot", label: "nav.copilot", icon: CopilotGlyph },
  { to: "/audit", label: "nav.audit", icon: LinkSimple },
  { to: "/statements", label: "nav.statements", icon: Files },
  { to: "/profile", label: "auth.account", icon: UserCircle },
];

/** The product mark: an N built from the bridge's steps, over the dashed safety floor, with the accent point the user signs. It sits on the rail, so its roles are the rail's. */
function Mark() {
  return (
    <svg aria-hidden viewBox="0 0 64 64" className="size-8 shrink-0">
      <rect width="64" height="64" rx="14" fill="var(--text)" />
      <g fill="var(--bg-rail)">
        <rect x="16" y="14" width="7" height="32" />
        <rect x="41" y="14" width="7" height="32" />
        <polygon points="16,14 23,14 48,46 41,46" />
      </g>
      <line x1="14" y1="53" x2="40" y2="53" stroke="var(--bg-rail)" strokeOpacity="0.55" strokeWidth="2.5" strokeDasharray="6 3" />
      <circle cx="49.5" cy="53" r="4.5" fill="var(--accent)" />
    </svg>
  );
}

function PersonaSwitcher({ group = "persona", compact = false }: { group?: string; compact?: boolean }) {
  const { persona, setPersona } = usePersona();
  const options: PersonaId[] = ["camila", "diego"];
  return (
    <fieldset className="min-w-0">
      <legend className={compact ? "sr-only" : "mb-2 text-xs font-medium text-ink-3"}>{t("app.viewingAs")}</legend>
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
              <input type="radio" name={group} value={id} checked={selected} onChange={() => setPersona(id)} className="sr-only" />
              <span className="text-sm font-medium">{t(`personas.${id}.name`)}</span>
              <span className={cn("text-xs text-ink-3", compact && "hidden")}>{t(`personas.${id}.detail`)}</span>
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

function SandboxSeal({ showData, phone = false }: { readonly showData: boolean; readonly phone?: boolean }) {
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
      {showData && (phone ? <span className="hidden sm:inline"><DataAsOf /></span> : <DataAsOf />)}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { pathname } = useLocation();
  useMarkLanded();
  // The phone header's height is whatever its second row needs; screens that fill the viewport read it from here.
  const headerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const header = headerRef.current;
    if (!header || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() => root.style.setProperty("--phone-header-h", `${header.offsetHeight}px`));
    observer.observe(header);
    return () => { observer.disconnect(); root.style.removeProperty("--phone-header-h"); };
  }, []);
  const signout = useMutation({ mutationFn: auth.signout });
  const isAccount = auth.mode === "accounts";
  const isMock = import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true";
  const showData = !isAccount || (!isMock && auth.me?.data_source === "persona");
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        {t("app.skipToContent")}
      </a>

      <aside className="rail hidden border-line bg-rail lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:border-r">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
          <Mark />
          <span className="text-base font-semibold tracking-[-0.01em] text-ink">{t("app.name")}</span>
        </div>
        {!isAccount && <div className="px-4 pb-4"><PersonaSwitcher /></div>}
        <nav aria-label={t("nav.label")} className="px-3 pb-3 lg:flex-1 lg:overflow-y-auto">
          <ul className="flex flex-col gap-1">
            {NAV.filter((item) => isAccount || item.to !== "/profile").map(({ to, label, icon: IconCmp }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex h-10 items-center justify-start gap-3 rounded-control px-3 text-left text-sm whitespace-nowrap transition-colors duration-150",
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
        {showData && <div className="border-t border-line px-5 py-4"><RuleCounter /></div>}
      </aside>

      <div className="flex min-w-0 flex-col">
        {/* Phone header: the brand on the left, the profile on the right, and the sandbox seal (or, in demo mode,
            the persona switch) under them. From lg the sidebar and the top bar below replace it. */}
        <header ref={headerRef} className="rail sticky top-0 z-30 border-b border-line bg-rail pt-[env(safe-area-inset-top)] lg:hidden">
          <div className="flex h-14 items-center justify-between gap-3 pr-2 pl-4">
            <div className="flex min-w-0 items-center gap-2.5">
              <Mark />
              <span className="truncate text-base font-semibold tracking-[-0.01em] text-ink">{t("app.name")}</span>
            </div>
            {isAccount && <div className="flex items-center gap-1">
              {isMock && <StatusBadge tone="warning">{t("auth.mock")}</StatusBadge>}
              <ProfileLink />
            </div>}
          </div>
          <div className="px-4 pb-2.5">
            {isAccount ? <SandboxSeal showData={showData} phone /> : <PersonaSwitcher group="persona-phone" compact />}
          </div>
        </header>
        <div className="hidden flex-wrap items-center justify-between gap-3 border-b border-line px-10 py-3 lg:flex">
          <SandboxSeal showData={showData} />
          {isAccount && <div className="flex flex-wrap items-center gap-3 text-sm">
            {isMock && <StatusBadge tone="warning">{t("auth.mock")}</StatusBadge>}
            <Button asChild variant="quiet" size="sm"><Link to="/profile">{t("auth.account")}</Link></Button>
            <Button variant="quiet" size="sm" onClick={() => signout.mutate()} disabled={signout.isPending} busy={signout.isPending}>
              {signout.isPending ? t("auth.signingOut") : t("auth.signout")}
            </Button>
          </div>}
        </div>
        {signout.isError && <div className="px-4 pt-4 sm:px-6 lg:px-10"><ErrorState error={signout.error} /></div>}
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 outline-none sm:px-6 lg:px-10 lg:py-10">
          {/* A new key per screen replays the fade-in, so moving between tabs never snaps. */}
          <div key={pathname} className="animate-[page-in_220ms_var(--ease-out)_both]">{children}</div>
        </main>
        <footer className={cn("px-4 pb-[calc(6.5rem+env(safe-area-inset-bottom))] text-xs text-ink-3 sm:px-6 lg:px-10 lg:pb-6", pathname === "/copilot" && "max-lg:hidden")}>{t(isAccount ? "auth.footer" : "app.footer")}</footer>
      </div>

      <MobileBar isAccount={isAccount} onSignout={() => signout.mutate()} signingOut={signout.isPending} />
    </div>
  );
}
