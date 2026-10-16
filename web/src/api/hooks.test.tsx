import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PersonaProvider, usePersona } from "./hooks";

function Probe() {
  const { persona, sessionId, newSession, setPersona } = usePersona();
  return (
    <>
      <output aria-label="session">{sessionId}</output>
      <button onClick={newSession}>new</button>
      <button onClick={() => setPersona(persona === "camila" ? "diego" : "camila")}>switch</button>
    </>
  );
}

function renderProbe() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PersonaProvider>
        <Probe />
      </PersonaProvider>
    </QueryClientProvider>,
  );
}

const session = () => screen.getByLabelText("session").textContent;

describe("PersonaProvider sessions", () => {
  beforeEach(() => sessionStorage.clear());

  it("keeps one session per persona and tab, and newSession replaces it", async () => {
    renderProbe();
    const first = session();
    expect(first).toMatch(/^ui-camila-/);
    expect(sessionStorage.getItem("nl.session.camila")).toBe(first);

    await userEvent.click(screen.getByText("new"));
    const second = session();
    expect(second).toMatch(/^ui-camila-/);
    expect(second).not.toBe(first);
    expect(sessionStorage.getItem("nl.session.camila")).toBe(second);

    await userEvent.click(screen.getByText("switch"));
    expect(session()).toMatch(/^ui-diego-/);
    await userEvent.click(screen.getByText("switch"));
    expect(session()).toBe(second); // back to Camila's current conversation, not a new one
  });
});
