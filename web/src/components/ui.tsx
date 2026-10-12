/**
 * Base components. One vocabulary across every screen: same button shape, same state badges,
 * same money rendering. Status is always icon + words, never color alone.
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Slot } from "@radix-ui/react-slot";
import * as Popover from "@radix-ui/react-popover";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { ArrowClockwise, CheckCircle, CircleNotch, Info, Prohibit, SealCheck, Warning, WarningOctagon } from "@phosphor-icons/react";
import { ApiError, NetworkError, type Fact } from "@/api/client";
import { formatAmount, formatMoney, moneyForSpeech } from "@/lib/format";
import { t } from "@/i18n";

// Teach the merger our custom tokens so `text-hero` (a size) is not dropped next to `text-ink` (a color).
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["hero"] }],
      rounded: [{ rounded: ["control", "object"] }],
      shadow: [{ shadow: ["object"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ---- Button ------------------------------------------------------------------------------------

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-control text-sm font-medium whitespace-nowrap select-none " +
    "transition-[background-color,border-color,color,transform] duration-150 ease-out " +
    "disabled:cursor-not-allowed aria-disabled:cursor-not-allowed",
  {
    variants: {
      variant: {
        primary: "bg-accent text-on-accent hover:bg-accent-hover active:scale-[0.97] disabled:bg-control aria-disabled:opacity-60",
        /** For actions that touch money: no press scale, only color. */
        money: "bg-accent text-on-accent hover:bg-accent-hover disabled:bg-control aria-disabled:opacity-60",
        secondary: "bg-surface text-ink border border-control hover:bg-canvas active:scale-[0.97] aria-disabled:opacity-60",
        quiet: "text-ink-2 hover:text-ink hover:bg-rail",
        danger: "bg-danger text-white hover:opacity-90",
      },
      size: { sm: "h-8 px-3", md: "h-10 px-4", lg: "h-11 px-5 text-base" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  asChild?: boolean;
  busy?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ className, variant, size, asChild, busy, children, ...props }, ref) {
  if (asChild) {
    // Slot needs exactly one child (e.g. a router Link); a link is never busy.
    return (
      <Slot ref={ref} className={cn(button({ variant, size }), className)} {...props}>
        {children}
      </Slot>
    );
  }
  return (
    <button ref={ref} className={cn(button({ variant, size }), className)} aria-busy={busy || undefined} {...props}>
      {busy && <CircleNotch aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />}
      {children}
    </button>
  );
});

// ---- Status --------------------------------------------------------------------------------------

export type Tone = "positive" | "warning" | "danger" | "neutral" | "accent";
const toneClass: Record<Tone, string> = {
  positive: "bg-positive-bg text-positive",
  warning: "bg-warning-bg text-warning",
  danger: "bg-danger-bg text-danger",
  neutral: "bg-rail text-ink-2",
  accent: "bg-accent-soft text-accent",
};
const toneIcon: Record<Tone, typeof Info> = {
  positive: CheckCircle,
  warning: Warning,
  danger: WarningOctagon,
  neutral: Info,
  accent: SealCheck,
};

export function StatusBadge({ tone, children, icon }: { tone: Tone; children: ReactNode; icon?: typeof Info }) {
  const Icon = icon ?? toneIcon[tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", toneClass[tone])}>
      <Icon aria-hidden weight="bold" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

/** An inline notice. The icon and title carry the meaning; color only reinforces it. */
export function Notice({ tone, title, children, icon }: { tone: Tone; title: ReactNode; children?: ReactNode; icon?: typeof Info }) {
  const Icon = icon ?? toneIcon[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-control px-4 py-3", toneClass[tone])}>
      <Icon aria-hidden weight="bold" className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold">{title}</p>
        {children && <div className="mt-0.5 text-ink-2">{children}</div>}
      </div>
    </div>
  );
}

export { Prohibit, SealCheck };

// ---- Layout ----------------------------------------------------------------------------------------

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 pb-8">
      <div className="max-w-3xl">
        <h1 id="page-title" className="text-2xl font-semibold text-ink">
          {title}
        </h1>
        {subtitle && <p className="mt-2 text-base text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-3">{actions}</div>}
    </header>
  );
}

/** A titled region on the canvas. Sections are separated by space and rules, not nested cards. */
export function Section({
  title,
  subtitle,
  children,
  className,
  aside,
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  className?: string;
  aside?: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section aria-labelledby={headingId} className={cn("min-w-0", className)}>
      {(title || aside) && (
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            {title && (
              <h2 id={headingId} className="text-lg font-semibold text-ink">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-sm text-ink-3">{subtitle}</p>}
          </div>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Surface({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-object border border-line bg-surface", className)}>{children}</div>;
}

// ---- Money with provenance -------------------------------------------------------------------------

export interface ProvenanceInfo {
  fact?: Fact;
  snapshotId?: string | null;
  paramsVersion?: string;
}

/**
 * A money value from the engine. Focus or hover reveals where it came from (snapshot, parameters,
 * derivation), replacing the repeated "how it was computed" rail with a mark on each number.
 */
export function Money({
  amount,
  currency,
  provenance,
  className,
  signed,
  bare,
}: {
  amount: number;
  currency: string;
  provenance?: ProvenanceInfo;
  className?: string;
  signed?: boolean;
  /** Omit the code visually when the surrounding layout already shows it; speech keeps it. */
  bare?: boolean;
}) {
  const text = bare ? formatAmount(amount, currency, { signed }) : formatMoney(amount, currency, { signed });
  const value = (
    <span className={cn("num whitespace-nowrap", className)} aria-label={moneyForSpeech(amount, currency)}>
      {text}
    </span>
  );
  if (!provenance) return value;
  return (
    <Popover.Root>
      <Popover.Trigger
        className="cursor-help rounded-sm decoration-control decoration-dotted underline-offset-4 hover:underline focus-visible:underline"
        aria-label={`${moneyForSpeech(amount, currency)}. ${t("provenance.label")}`}
      >
        <span className={cn("num whitespace-nowrap", className)}>{text}</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={8}
          collisionPadding={16}
          className="z-50 w-72 rounded-object border border-line bg-surface p-4 text-sm text-ink-2 shadow-object data-[state=open]:animate-in"
        >
          <p className="font-medium text-ink">{t("provenance.engine")}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
            {provenance.fact && (
              <>
                <dt className="text-ink-3">{t("provenance.derivation")}</dt>
                <dd>{provenance.fact.derivation}</dd>
              </>
            )}
            {provenance.snapshotId && (
              <>
                <dt className="text-ink-3">{t("provenance.snapshot")}</dt>
                <dd className="truncate font-mono text-xs">{provenance.snapshotId}</dd>
              </>
            )}
            {provenance.paramsVersion && (
              <>
                <dt className="text-ink-3">{t("provenance.params")}</dt>
                <dd className="font-mono text-xs">{provenance.paramsVersion}</dd>
              </>
            )}
          </dl>
          <Popover.Arrow className="fill-surface" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ---- Loading, empty and error states ---------------------------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-control bg-rail motion-reduce:animate-none", className)} />;
}

export function Loading({ label = t("common.loading"), className }: { label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("space-y-3", className)}>
      <span className="sr-only">{label}</span>
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-6 w-1/2" />
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-object border border-dashed border-control/60 px-6 py-8">
      <p className="text-base font-medium text-ink">{title}</p>
      {children && <div className="max-w-prose text-sm text-ink-2">{children}</div>}
      {action}
    </div>
  );
}

/** Turns whatever went wrong into words the user can act on. */
export function describeError(error: unknown): string {
  if (error instanceof NetworkError) return t("errors.network");
  if (error instanceof ApiError) {
    const d = error.detail;
    if (d.status === "INSUFFICIENT_DATA") return t("errors.insufficientData", { missing: (d.missing ?? []).join(", ") || "unknown" });
    if (d.message) return d.message;
    if (d.reason) return t("errors.generic", { message: d.reason });
    return t("errors.generic", { message: error.message });
  }
  return t("errors.generic", { message: error instanceof Error ? error.message : String(error) });
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Notice tone="danger" title={describeError(error)}>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          <ArrowClockwise aria-hidden className="size-4" />
          {t("common.retry")}
        </Button>
      )}
    </Notice>
  );
}
