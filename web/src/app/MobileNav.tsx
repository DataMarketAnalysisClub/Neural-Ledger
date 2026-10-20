import { useState, type CSSProperties } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import * as Popover from "@radix-ui/react-popover";
import { CalendarDots, ChartLineDown, DotsThreeCircle, Files, LinkSimple, PiggyBank, PlugsConnected, Receipt, SignOut, TrendUp, UserCircle, type Icon } from "@phosphor-icons/react";
import { CopilotAvatar } from "@/components/CopilotAvatar";
import { t, type MessageKey } from "@/i18n";
import { Button, cn } from "@/components/ui";
import { LanguagePicker } from "@/components/LanguagePicker";

/**
 * The phone chrome (below lg): a header that carries the profile and a bottom bar with four destinations, the
 * Copilot raised in the middle, and a More sheet that unfolds upward from the bar. The sidebar takes over from lg.
 */
interface Tab {
  readonly to: string;
  readonly label: MessageKey;
  readonly icon: Icon;
}

const LEFT: readonly Tab[] = [
  { to: "/", label: "nav.overview", icon: ChartLineDown },
  { to: "/commitments", label: "nav.commitments", icon: CalendarDots },
];
const COPILOT = { to: "/copilot", label: "nav.copilot" } as const;
const RIGHT: readonly Tab[] = [{ to: "/plan", label: "nav.planShort", icon: PiggyBank }];
const MORE: readonly Tab[] = [
  { to: "/simulator", label: "nav.simulator", icon: Receipt },
  { to: "/statements", label: "nav.statements", icon: Files },
  { to: "/investments", label: "nav.investments", icon: TrendUp },
  { to: "/connections", label: "nav.connections", icon: PlugsConnected },
  { to: "/audit", label: "nav.audit", icon: LinkSimple },
];

const tabClass = "group relative flex h-14 w-full flex-col items-center justify-center gap-1 text-[11px] leading-none font-medium transition-[color,transform] duration-150 active:scale-95 motion-reduce:active:scale-100";

function Indicator({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden
      className={cn("absolute top-0 h-0.5 w-8 origin-center rounded-full bg-accent transition-transform duration-200 ease-out", active ? "scale-x-100" : "scale-x-0")}
    />
  );
}

function BarLink({ tab }: { tab: Tab }) {
  const Glyph = tab.icon;
  return (
    <NavLink to={tab.to} end={tab.to === "/"} className={({ isActive }) => cn(tabClass, isActive ? "text-ink" : "text-ink-2")}>
      {({ isActive }) => (
        <>
          <Indicator active={isActive} />
          <Glyph aria-hidden weight={isActive ? "fill" : "regular"} className={cn("size-6 transition-colors", isActive && "text-accent")} />
          <span className="max-w-full truncate px-0.5">{t(tab.label)}</span>
        </>
      )}
    </NavLink>
  );
}

/** The Copilot is the product's main action: its round avatar sits in the middle of the bar, raised above it. */
function FeaturedLink({ tab }: { tab: typeof COPILOT }) {
  return (
    <NavLink to={tab.to} data-featured="true" className={({ isActive }) => cn("group relative -mt-5 flex w-full flex-col items-center gap-1 pb-1.5 text-[11px] leading-none font-semibold transition-colors", isActive ? "text-accent" : "text-ink-2")}>
      {({ isActive }) => (
        <>
          <span className={cn("rounded-full ring-4 ring-surface transition-transform duration-200 ease-out group-active:scale-90 motion-reduce:group-active:scale-100", isActive && "scale-105")}>
            <CopilotAvatar className={cn("size-14 rounded-full", isActive && "outline outline-2 outline-offset-2 outline-accent")} />
          </span>
          <span>{t(tab.label)}</span>
        </>
      )}
    </NavLink>
  );
}

export function MobileBar({ isAccount, onSignout, signingOut }: { isAccount: boolean; onSignout: () => void; signingOut: boolean }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const moreActive = MORE.some(({ to }) => pathname.startsWith(to));
  return (
    <>
      {/* Dims the screen behind the sheet; always mounted so it fades both ways. */}
      <div
        aria-hidden
        data-open={open}
        className="pointer-events-none fixed inset-0 z-30 bg-ink/30 opacity-0 transition-opacity duration-200 data-[open=true]:pointer-events-auto data-[open=true]:opacity-100 lg:hidden"
      />
      <nav aria-label={t("nav.primary")} className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden">
        <ul className="grid grid-cols-[1.15fr_1.15fr_1fr_1.15fr_1.15fr] items-end">
          {LEFT.map((tab) => <li key={tab.to} className="flex"><BarLink tab={tab} /></li>)}
          <li className="flex"><FeaturedLink tab={COPILOT} /></li>
          {RIGHT.map((tab) => <li key={tab.to} className="flex"><BarLink tab={tab} /></li>)}
          <li className="flex">
            <Popover.Root open={open} onOpenChange={setOpen}>
              <Popover.Trigger className={cn(tabClass, open || moreActive ? "text-ink" : "text-ink-2")}>
                <Indicator active={open || moreActive} />
                <DotsThreeCircle aria-hidden weight={open || moreActive ? "fill" : "regular"} className={cn("size-6 transition-[color,transform] duration-200", (open || moreActive) && "text-accent", open && "rotate-90 motion-reduce:rotate-0")} />
                <span>{t("nav.more")}</span>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  aria-label={t("nav.more")}
                  side="top"
                  align="end"
                  sideOffset={30}
                  collisionPadding={12}
                  className="z-50 w-[min(calc(100vw-1.5rem),26rem)] origin-[var(--radix-popover-content-transform-origin)] rounded-object border border-line bg-surface p-3 shadow-object outline-none data-[state=closed]:animate-[sheet-out_150ms_ease-in_forwards] data-[state=open]:animate-[sheet-in_240ms_var(--ease-out)] lg:hidden"
                >
                  <ul className="grid grid-cols-2 gap-2">
                    {MORE.map(({ to, label, icon: Glyph }, index) => (
                      <li key={to} style={{ "--i": index } as CSSProperties} className="animate-[rise_260ms_var(--ease-out)_both] [animation-delay:calc(var(--i)*45ms+60ms)] [&:last-child:nth-child(odd)]:col-span-2">
                        <Popover.Close asChild>
                          <Link
                            to={to}
                            aria-current={pathname.startsWith(to) ? "page" : undefined}
                            className={cn("flex min-h-[4.5rem] flex-col justify-between gap-2 rounded-control border border-line p-3 text-sm font-medium transition-[background-color,transform] duration-150 active:scale-[0.97] motion-reduce:active:scale-100", pathname.startsWith(to) ? "bg-canvas text-ink" : "bg-surface text-ink-2 hover:bg-canvas")}
                          >
                            <Glyph aria-hidden className="size-5 text-ink" />
                            {t(label)}
                          </Link>
                        </Popover.Close>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex animate-[rise_260ms_var(--ease-out)_both] items-center justify-between gap-3 border-t border-line pt-3 [animation-delay:200ms]">
                    <LanguagePicker />
                    {isAccount && (
                      <Button variant="quiet" onClick={onSignout} disabled={signingOut} busy={signingOut}>
                        <SignOut aria-hidden className="size-5" />
                        {signingOut ? t("auth.signingOut") : t("auth.signout")}
                      </Button>
                    )}
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </li>
        </ul>
      </nav>
    </>
  );
}

/** The profile lives in the header on a phone, one tap from every screen. */
export function ProfileLink() {
  return (
    <NavLink to="/profile" className={({ isActive }) => cn("flex size-11 items-center justify-center rounded-full transition-colors duration-150 active:scale-95", isActive ? "bg-surface text-accent ring-1 ring-line" : "text-ink-2 hover:bg-surface/60 hover:text-ink")}>
      {({ isActive }) => (
        <>
          <UserCircle aria-hidden weight={isActive ? "fill" : "regular"} className="size-7" />
          <span className="sr-only">{t("auth.account")}</span>
        </>
      )}
    </NavLink>
  );
}

