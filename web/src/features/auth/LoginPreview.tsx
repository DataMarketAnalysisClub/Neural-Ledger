import { useEffect, useState } from "react";
import { cn } from "@/components/ui";
import { useMediaQuery } from "@/lib/useMediaQuery";

/** Every screen of the app, as the sign-in's backdrop. Captured with the synthetic persona Camila. */
export const PREVIEW_SCREENS = [
  { name: "Overview", src: "/login/overview.webp" },
  { name: "Commitments", src: "/login/commitments.webp" },
  { name: "Purchase check", src: "/login/purchase-check.webp" },
  { name: "Savings plan", src: "/login/savings-plan.webp" },
  { name: "Copilot", src: "/login/copilot.webp" },
  { name: "Audit trail", src: "/login/audit-trail.webp" },
  { name: "Statements", src: "/login/statements.webp" },
  { name: "Profile", src: "/login/profile.webp" },
] as const;

export const PREVIEW_INTERVAL_MS = 4000;

/**
 * The real app peeking in from the corner, changing screen every few seconds: the new one rises in while the old one
 * lifts away and fades. Decorative (the words next to it say what the app does), it stays on the first screen for
 * anyone who prefers reduced motion, and it waits while the tab is hidden.
 */
export function LoginPreview({ className }: { className?: string }) {
  const [{ index, previous }, setShown] = useState<{ index: number; previous: number | null }>({ index: 0, previous: null });
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");

  useEffect(() => {
    if (reduced) return;
    const timer = setInterval(() => {
      if (document.hidden) return;
      setShown((s) => ({ index: (s.index + 1) % PREVIEW_SCREENS.length, previous: s.index }));
    }, PREVIEW_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [reduced]);

  return (
    <div aria-hidden="true" className={cn("relative overflow-hidden animate-[rise_900ms_var(--ease-out)_both] motion-reduce:animate-none", className)}>
      {PREVIEW_SCREENS.map((screen, i) => {
        const state = i === index ? "active" : i === previous ? "leaving" : "waiting";
        return (
          <img
            key={screen.src}
            src={screen.src}
            alt=""
            data-state={state}
            loading={i === 0 ? "eager" : "lazy"}
            className={cn(
              "absolute top-0 left-0 min-h-full w-[108%] max-w-none rounded-tl-[calc(10*var(--u))] border border-r-0 border-b-0 border-on-accent/35 bg-surface object-cover object-left-top transition-[opacity,transform] duration-700 ease-out motion-reduce:transition-none",
              state === "active" && "translate-y-0 opacity-100",
              state === "leaving" && "-translate-y-2 opacity-0",
              state === "waiting" && "translate-y-5 opacity-0",
            )}
          />
        );
      })}
    </div>
  );
}
