import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { AppShell } from "./AppShell";
import { MobileLanding, resetMobileLanding } from "./mobileLanding";

/** The phone layout: a header with the profile, a bottom bar with the Copilot in the middle, and a More sheet. */
let auth: { mode: "demo" | "accounts"; me: { data_source: string } | null; signout: () => Promise<void> };
vi.mock("@/features/auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/api/hooks", () => ({
  useFinancialState: () => ({ data: undefined }),
  useHealth: () => ({ data: { mode: "offline", language_model: "scripted" } }),
  usePersona: () => ({ persona: "camila", setPersona: vi.fn() }),
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { vi.restoreAllMocks(); resetMobileLanding(); });

function mount(path = "/") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell><Routes><Route path="*" element={<p>screen</p>} /></Routes></AppShell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signedIn() {
  auth = { mode: "accounts", me: { data_source: "persona" }, signout: vi.fn().mockResolvedValue(undefined) };
}

describe("phone header", () => {
  it("puts the profile in the header, not in the bottom bar", () => {
    signedIn();
    mount();
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Profile" })).toHaveAttribute("href", "/profile");
    const bar = screen.getByRole("navigation", { name: "Primary" });
    expect(within(bar).queryByRole("link", { name: "Profile" })).not.toBeInTheDocument();
  });

  it("keeps the persona switch reachable in demo mode, where there is no profile", () => {
    auth = { mode: "demo", me: null, signout: vi.fn() };
    mount();
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("radio", { name: /Diego/ })).toBeInTheDocument();
    expect(within(header).queryByRole("link", { name: "Profile" })).not.toBeInTheDocument();
  });
});

describe("Copilot icon", () => {
  it("is the brand mark in the sidebar, drawn like the other nav icons", () => {
    signedIn();
    mount();
    const sidebar = screen.getByRole("navigation", { name: "Main" });
    const glyph = within(sidebar).getByRole("link", { name: "Copilot" }).querySelector("svg")!;
    expect(glyph).toHaveAttribute("data-glyph", "copilot");
    expect(glyph).toHaveAttribute("aria-hidden", "true");
  });

  it("is the round avatar in the middle of the bottom bar", () => {
    signedIn();
    mount();
    const bar = screen.getByRole("navigation", { name: "Primary" });
    const avatar = within(bar).getByRole("link", { name: "Copilot" }).querySelector("svg")!;
    expect(avatar).toHaveAttribute("data-shape", "round");
  });
});

describe("bottom bar", () => {
  it("has four destinations and More, with the Copilot in the middle", () => {
    signedIn();
    mount();
    const bar = screen.getByRole("navigation", { name: "Primary" });
    const items = within(bar).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(within(items[0]!).getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
    expect(within(items[1]!).getByRole("link", { name: "Commitments" })).toHaveAttribute("href", "/commitments");
    expect(within(items[2]!).getByRole("link", { name: "Copilot" })).toHaveAttribute("href", "/copilot");
    expect(within(items[3]!).getByRole("link", { name: "Plan" })).toHaveAttribute("href", "/plan");
    expect(within(items[4]!).getByRole("button", { name: "More" })).toBeInTheDocument();
  });

  it("marks the current screen and highlights the Copilot", () => {
    signedIn();
    mount("/copilot");
    const bar = screen.getByRole("navigation", { name: "Primary" });
    const copilot = within(bar).getByRole("link", { name: "Copilot" });
    expect(copilot).toHaveAttribute("aria-current", "page");
    expect(copilot).toHaveAttribute("data-featured", "true");
    expect(within(bar).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });
});

describe("More sheet", () => {
  it("opens upward from the bar with the rest of the screens and signs out", async () => {
    signedIn();
    const user = userEvent.setup();
    mount();
    const more = screen.getByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "false");

    await user.click(more);

    const sheet = await screen.findByRole("dialog", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(sheet).toHaveAttribute("data-side", "top");
    expect(within(sheet).getByRole("link", { name: "Purchase check" })).toHaveAttribute("href", "/simulator");
    expect(within(sheet).getByRole("link", { name: "Statements" })).toHaveAttribute("href", "/statements");
    expect(within(sheet).getByRole("link", { name: "Audit trail" })).toHaveAttribute("href", "/audit");
    await user.click(within(sheet).getByRole("button", { name: "Sign out" }));
    expect(auth.signout).toHaveBeenCalled();
  });

  it("closes on Escape and when a screen is chosen", async () => {
    signedIn();
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "More" }));
    await screen.findByRole("dialog", { name: "More" });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "More" })).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(within(await screen.findByRole("dialog", { name: "More" })).getByRole("link", { name: "Audit trail" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "More" })).not.toBeInTheDocument());
  });

  it("has no accessibility violations while open", async () => {
    signedIn();
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "More" }));
    const sheet = await screen.findByRole("dialog", { name: "More" });
    expect((await axe(sheet)).violations).toEqual([]);
    expect((await axe(screen.getByRole("navigation", { name: "Primary" }))).violations).toEqual([]);
  });
});

describe("landing on a phone", () => {
  function landing(phone: boolean) {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: phone && query.includes("max-width"), media: query, addEventListener() {}, removeEventListener() {} }));
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<MobileLanding><p>overview screen</p></MobileLanding>} />
          <Route path="/copilot" element={<p>copilot screen</p>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("opens on the Copilot the first time on a phone", () => {
    landing(true);
    expect(screen.getByText("copilot screen")).toBeInTheDocument();
  });

  it("keeps the Overview on a wide screen", () => {
    landing(false);
    expect(screen.getByText("overview screen")).toBeInTheDocument();
  });
});
