import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { accountsApi } from "@/api/accounts";
import { PersonaProvider } from "@/api/hooks";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { OnboardingPage } from "./OnboardingPage";

function Guard() {
  const auth = useAuth();
  if (auth.pending) return <div role="status">Loading</div>;
  return <PersonaProvider><Routes>
    <Route path="/onboarding" element={<OnboardingPage />} />
    <Route path="/profile" element={<ProfilePage />} />
  </Routes></PersonaProvider>;
}

function mount(initial: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><AuthProvider><Guard /></AuthProvider></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => vi.stubEnv("VITE_ACCOUNTS_MOCK", "true"));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("versioned questionnaire", () => {
  it("renders labelled choices without axe violations", async () => {
    await accountsApi.signup({ email: "question-axe@example.invalid", password: "synthetic-password", display_name: "Axe Tester", sandbox_acknowledged: true });
    const { container } = mount("/onboarding");
    await waitFor(() => expect(screen.getByRole("group", { name: /Of money left after bills/ })).toBeInTheDocument());

    const result = await axe(container);

    expect(result.violations).toEqual([]);
    expect(screen.getByRole("link", { name: "Later" })).toBeInTheDocument();
  });

  it("submits only versioned ids and displays the returned tolerance", async () => {
    await accountsApi.signup({ email: "question-submit@example.invalid", password: "synthetic-password", display_name: "Question Tester", sandbox_acknowledged: true });
    mount("/onboarding");
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Your saving preferences" })).toBeInTheDocument());

    for (const option of ["Most of it", "Keep it, that is what it is for", "Reaching the goal on time", "Calm", "Yes, regularly"]) {
      await user.click(screen.getByRole("radio", { name: option }));
      await user.click(screen.getByRole("button", { name: option === "Yes, regularly" ? "Save answers" : "Next" }));
    }

    await waitFor(() => expect(screen.getByRole("heading", { name: "Your profile" })).toBeInTheDocument());
    expect(screen.getByText("Aggressive")).toBeInTheDocument();
    expect(screen.getByText("Answered with pq-0.1")).toBeInTheDocument();
  });

  it("shows a timeline above the card that only lets a person go back to answered questions", async () => {
    await accountsApi.signup({ email: "question-timeline@example.invalid", password: "synthetic-password", display_name: "Timeline Tester", sandbox_acknowledged: true });
    mount("/onboarding");
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("group", { name: /Of money left after bills/ })).toBeInTheDocument());

    const timeline = screen.getByRole("list", { name: "Progress" });
    expect(within(timeline).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Question 1 of 5, current" })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: "Question 2 of 5, not reached yet" })).toBeDisabled();
    expect(timeline.compareDocumentPosition(screen.getByRole("group", { name: /Of money left after bills/ })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(screen.getByRole("radio", { name: "Most of it" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("group", { name: /If the rule leaves less room/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Question 2 of 5, current" })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: "Question 3 of 5, not reached yet" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Question 1 of 5, answered" }));
    expect(screen.getByRole("group", { name: /Of money left after bills/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Most of it" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Question 2 of 5, not answered yet" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Question 3 of 5, not reached yet" })).toBeDisabled();
  });

  it("stands alone: no app navigation around the questions", async () => {
    await accountsApi.signup({ email: "question-alone@example.invalid", password: "synthetic-password", display_name: "Alone Tester", sandbox_acknowledged: true });
    mount("/onboarding");
    await waitFor(() => expect(screen.getByRole("group", { name: /Of money left after bills/ })).toBeInTheDocument());

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("keeps a new account's profile empty, editable and without a sample-data action", async () => {
    await accountsApi.signup({ email: "empty-profile@example.invalid", password: "synthetic-password", display_name: "Empty Tester", sandbox_acknowledged: true });
    const permitted = vi.spyOn(accountsApi, "permitted");
    const { container } = mount("/profile");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Your profile" })).toBeInTheDocument());

    expect(screen.getByText(/Capacity is unavailable until financial data is available\. Import at least 7 months/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "No financial data yet" })).toHaveTextContent("A new account starts empty.");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/sample/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Financial capacity", { exact: false })).not.toBeInTheDocument();
    expect(permitted).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Answer the questionnaire" })).toHaveAttribute("href", "/onboarding");
    expect((await axe(container)).violations).toEqual([]);

    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Renamed Tester");
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Renamed Tester" })).toBeInTheDocument());
    expect(await accountsApi.me()).toMatchObject({ data_source: "empty" });
  });
});
