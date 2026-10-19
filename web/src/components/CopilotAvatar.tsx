import { cn } from "@/components/ui";

export type AvatarState = "idle" | "thinking" | "responding";
export type AvatarShape = "round" | "tile";

/**
 * The Copilot's face: the product mark. At rest its point breathes, while the engine is consulted it runs along
 * the dashed floor, and when the answer lands the N glows. Decorative (the words carry the meaning), flat, and
 * still under reduced motion. `still` freezes it, so only the live turn of a long conversation moves. Round, like a
 * profile picture, beside the message; `tile` is the squared mark.
 */
export function CopilotAvatar({ state = "idle", still = false, shape = "round", className }: { state?: AvatarState; still?: boolean; shape?: AvatarShape; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 64 64"
      data-state={state}
      data-still={still ? "true" : undefined}
      data-shape={shape}
      className={cn("copilot-avatar size-8 shrink-0", className)}
    >
      <rect width="64" height="64" rx={shape === "round" ? 32 : 14} fill="var(--rail-bg)" />
      {/* In the circle the mark is drawn a little smaller, so its point stays inside the edge. */}
      <g transform={shape === "round" ? "translate(32 32) scale(0.86) translate(-32 -32)" : undefined}>
      <g className="avatar-n" fill="var(--rail-text)">
        <rect x="16" y="14" width="7" height="32" />
        <rect x="41" y="14" width="7" height="32" />
        <polygon points="16,14 23,14 48,46 41,46" />
      </g>
      <line className="avatar-dash" x1="14" y1="53" x2="40" y2="53" stroke="var(--rail-text)" strokeOpacity="0.55" strokeWidth="2.5" />
      <circle className="avatar-dot" cx="49.5" cy="53" r="4.5" fill="var(--rail-accent)" />
      </g>
    </svg>
  );
}
