import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GuidePanel, type GuideStep } from "./OverviewGuide";

const steps: GuideStep[] = [
  { target: "a", title: "First", body: "About a" },
  { target: "b", title: "Second", body: "About b" },
];

function Page({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  return (
    <>
      <div id="a">region a</div>
      <div id="b">region b</div>
      <GuidePanel steps={steps} step={step} onStep={setStep} onClose={onClose} />
    </>
  );
}

describe("GuidePanel", () => {
  it("walks the steps, outlining only the region the open step explains", async () => {
    const onClose = vi.fn();
    render(<Page onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "First" })).toHaveTextContent("Step 1 of 2");
    expect(screen.getByRole("heading", { name: "First" })).toHaveFocus();
    expect(screen.getByText("region a")).toHaveClass("outline-2");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Second" })).toHaveTextContent("About b");
    expect(screen.getByText("region a")).not.toHaveClass("outline-2");
    expect(screen.getByText("region b")).toHaveClass("outline-2");

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes on Escape and with the close button", async () => {
    const onClose = vi.fn();
    render(<Page onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Close guide" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
