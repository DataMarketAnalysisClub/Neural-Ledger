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
 * The real app peeking in from the corner, turning pages: the next screen slides in from the right as the current one
 * slides out to the left, in one continuous motion. Decorative (the words next to it say what the app does), it stays
 * on the first screen for anyone who prefers reduced motion, and it waits while the tab is hidden.
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
              "absolute top-0 left-0 min-h-full w-[108%] max-w-none rounded-tl-[calc(10*var(--u))] border border-r-0 border-b-0 border-on-accent/35 bg-surface object-cover object-left-top will-change-transform",
              // Sliding states ease in and out together; a page waiting on the right snaps there with no transition.
              state === "active" && "translate-x-0 transition-transform duration-[900ms] ease-[cubic-bezier(0.65,0,0.35,1)] motion-reduce:transition-none",
              state === "leaving" && "-translate-x-full transition-transform duration-[900ms] ease-[cubic-bezier(0.65,0,0.35,1)] motion-reduce:transition-none",
              state === "waiting" && "translate-x-full transition-none",
            )}
          />
        );
      })}
    </div>
  );
}
