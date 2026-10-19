import { useEffect, useRef } from "react";
import { X } from "@phosphor-icons/react";
import { Button } from "@/components/ui";
import { t } from "@/i18n";

export interface GuideStep {
  /** The id of the element the step explains: it is scrolled into view and outlined while the step is open. */
  target: string;
  title: string;
  body: string;
}

/** Outline for the element the open step explains. */
const SPOT = ["rounded-object", "outline-2", "outline-offset-8", "outline-accent"];

/**
 * A walk through the page, one region per step. Not modal: the page stays readable and scrollable behind it.
 * Escape or the close button ends it; the caller gives focus back to the button that opened it.
 */
export function GuidePanel({ steps, step, onStep, onClose }: { steps: GuideStep[]; step: number; onStep: (step: number) => void; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const current = steps[Math.min(step, steps.length - 1)]!;
  const last = step >= steps.length - 1;

  useEffect(() => {
    heading.current?.focus();
    const target = document.getElementById(current.target);
    if (!target) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
    target.classList.add(...SPOT);
    return () => target.classList.remove(...SPOT);
  }, [current.target]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      {/* Room below the page, so the last regions can still scroll above the panel. Render the guide last. */}
      <div aria-hidden className="h-72" />
      <div role="dialog" aria-labelledby="guide-title" className="fixed inset-x-4 bottom-4 z-50 rounded-object border border-line bg-surface p-5 shadow-object sm:left-auto sm:w-[380px]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="num text-xs text-ink-3">{t("guide.progress", { step: step + 1, total: steps.length })}</p>
            <h2 id="guide-title" ref={heading} tabIndex={-1} className="mt-1 text-base font-semibold text-ink focus:outline-none">
              {current.title}
            </h2>
          </div>
          <Button variant="quiet" size="sm" onClick={onClose} aria-label={t("guide.close")} className="-mt-1 -mr-2 w-8 px-0">
            <X aria-hidden className="size-4" />
          </Button>
        </div>
        <p className="mt-2 text-sm text-ink-2">{current.body}</p>
        <div className="mt-5 flex items-center justify-between gap-3">
          <Button variant="quiet" size="sm" onClick={() => onStep(step - 1)} disabled={step === 0}>
            {t("guide.back")}
          </Button>
          <Button variant="primary" size="sm" onClick={last ? onClose : () => onStep(step + 1)}>
            {last ? t("guide.done") : t("guide.next")}
          </Button>
        </div>
      </div>
    </>
  );
}
