import { useEffect, type ReactNode } from "react";
import { Navigate } from "react-router-dom";

/**
 * On a phone the app opens on the Copilot, the one screen that answers a question outright. It happens once per
 * page load: the bar's Overview link must still lead to the Overview afterwards, and a wide screen never redirects.
 */
let landed = false;

export function resetMobileLanding() {
  landed = false;
}

/** Called by the shell once it is on screen: any later visit to "/" is a choice, not a landing. */
export function useMarkLanded() {
  useEffect(() => { landed = true; }, []);
}

function onPhone() {
  return typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1023px)").matches;
}

export function MobileLanding({ children }: { children: ReactNode }) {
  if (!landed && onPhone()) return <Navigate to="/copilot" replace />;
  return <>{children}</>;
}
