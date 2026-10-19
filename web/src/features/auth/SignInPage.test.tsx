import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { SignInPage, SignUpPage } from "./AuthPages";

const explore = vi.fn().mockResolvedValue(undefined);
vi.mock("./AuthProvider", () => ({ useAuth: () => ({ signin: vi.fn(), signup: vi.fn(), explore, mode: "accounts", me: null }) }));
afterEach(() => vi.clearAllMocks());

const mount = (page: "in" | "up" = "in") => render(<MemoryRouter>{page === "in" ? <SignInPage /> : <SignUpPage />}</MemoryRouter>);

describe("sign-in page", () => {
  it("keeps one h1, the form's, and puts the product's pitch beside it", () => {
    mount();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    const pitch = screen.getByRole("complementary");
    expect(within(pitch).getByText("Check any purchase against your future months.")).toBeInTheDocument();
    expect(within(pitch).getByText("Forecast, savings plan and a copilot that explains every number.")).toBeInTheDocument();
    expect(within(pitch).queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("names what the product does, as chips", () => {
    mount();
    const chips = within(screen.getByRole("complementary")).getByRole("list", { name: "What you can do" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Forecast", "Purchase check", "Savings plan", "Copilot"]);
  });

  it("shows the real app, page after page, as a decorative preview", () => {
    const { container } = mount();
    const preview = container.querySelector("aside div[aria-hidden='true']");
    expect(preview).not.toBeNull();
    const images = [...preview!.querySelectorAll("img")];
    expect(images).toHaveLength(8);
    expect(images[0]).toHaveAttribute("src", "/login/overview.webp");
    expect(images.every((img) => img.getAttribute("alt") === "")).toBe(true);
  });

  it("offers the demo personas beside each other under a divider, with the full names for assistive technology", async () => {
    mount();
    const group = screen.getByRole("group", { name: "Explore a demo persona" });
    expect(within(group).getByRole("button", { name: "Explore as Camila" })).toHaveTextContent("Camila");
    await userEvent.click(within(group).getByRole("button", { name: "Explore as Diego" }));
    expect(explore).toHaveBeenCalledWith("diego");
    expect(screen.getByText("or explore a demo persona")).toBeInTheDocument();
  });

  it("keeps the sandbox notice and the way to create an account", () => {
    mount();
    expect(screen.getByText("Sandbox only. Do not use real account information.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup");
  });

  it("has no accessibility violations on sign-in or sign-up", async () => {
    const first = mount();
    expect((await axe(first.container)).violations).toEqual([]);
    first.unmount();
    const second = mount("up");
    expect(screen.getByRole("heading", { level: 1, name: "Create an account" })).toBeInTheDocument();
    expect((await axe(second.container)).violations).toEqual([]);
  });
});
