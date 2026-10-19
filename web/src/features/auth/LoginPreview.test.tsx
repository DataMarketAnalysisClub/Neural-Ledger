import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import { LoginPreview, PREVIEW_SCREENS, PREVIEW_INTERVAL_MS } from "./LoginPreview";

function reducedMotion(on: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: on && query.includes("prefers-reduced-motion"), media: query, addEventListener() {}, removeEventListener() {} }));
}
const states = (container: HTMLElement) => [...container.querySelectorAll("img")].map((img) => img.getAttribute("data-state"));
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

beforeEach(() => { vi.useFakeTimers(); reducedMotion(false); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); Object.defineProperty(document, "hidden", { configurable: true, value: false }); });

describe("LoginPreview", () => {
  it("shows every screen of the app, decoratively", () => {
    const { container } = render(<LoginPreview />);
    expect(PREVIEW_SCREENS.map((s) => s.name)).toEqual(["Overview", "Commitments", "Purchase check", "Savings plan", "Copilot", "Audit trail", "Statements", "Profile"]);
    const images = [...container.querySelectorAll("img")];
    expect(images).toHaveLength(PREVIEW_SCREENS.length);
    expect(images.every((img) => img.getAttribute("alt") === "")).toBe(true);
    expect(images[0]).toHaveAttribute("src", "/login/overview.webp");
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  it("starts on the first screen and moves to the next on a timer, then comes back to the start", () => {
    const { container } = render(<LoginPreview />);
    expect(states(container)).toEqual(["active", ...Array(7).fill("waiting")]);

    tick(PREVIEW_INTERVAL_MS);
    expect(states(container).slice(0, 3)).toEqual(["leaving", "active", "waiting"]);

    tick(PREVIEW_INTERVAL_MS * 7);
    expect(states(container)[0]).toBe("active");
    expect(states(container).filter((s) => s === "active")).toHaveLength(1);
  });

  it("does not change on its own when the person prefers reduced motion", () => {
    reducedMotion(true);
    const { container } = render(<LoginPreview />);
    tick(PREVIEW_INTERVAL_MS * 5);
    expect(states(container)).toEqual(["active", ...Array(7).fill("waiting")]);
  });

  it("waits while the tab is hidden", () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    const { container } = render(<LoginPreview />);
    tick(PREVIEW_INTERVAL_MS * 3);
    expect(states(container)[0]).toBe("active");
  });

  it("stops its timer when it leaves the page", () => {
    const { unmount } = render(<LoginPreview />);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
