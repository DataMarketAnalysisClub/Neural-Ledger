import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { CopilotAvatar } from "./CopilotAvatar";

describe("CopilotAvatar", () => {
  it("is decorative: hidden from assistive technology, with the state in a data attribute", () => {
    const { container } = render(<CopilotAvatar state="thinking" />);
    const avatar = container.querySelector("svg")!;
    expect(avatar).toHaveAttribute("aria-hidden", "true");
    expect(avatar).toHaveAttribute("data-state", "thinking");
  });

  it("rests when it is not given a state", () => {
    const { container } = render(<CopilotAvatar />);
    expect(container.querySelector("svg")).toHaveAttribute("data-state", "idle");
  });

  it("can stay still, so a long conversation is not a wall of motion", () => {
    const { container } = render(<CopilotAvatar still />);
    expect(container.querySelector("svg")).toHaveAttribute("data-still", "true");
  });

  it("is round by default, like a profile picture, and can be the squared mark", () => {
    const { container, rerender } = render(<CopilotAvatar />);
    expect(container.querySelector("svg")).toHaveAttribute("data-shape", "round");
    rerender(<CopilotAvatar shape="tile" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-shape", "tile");
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<CopilotAvatar />);
    expect((await axe(container)).violations).toEqual([]);
  });
});
