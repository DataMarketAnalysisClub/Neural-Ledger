import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { tDynamic } from "@/i18n";
import { PLACEHOLDERS, RedactedText, redactedPlainText, splitPlaceholders } from "./redaction";

function chips(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll("[data-placeholder]")].map((chip) => chip.getAttribute("data-placeholder"));
}

describe("RedactedText", () => {
  it("renders each placeholder as a translated chip and keeps the rest as text", () => {
    const { container } = render(
      <p>
        <RedactedText text="[NUMBER] Transf a [PERSON] [ID]" />
      </p>,
    );
    expect(chips(container)).toEqual(["NUMBER", "PERSON", "ID"]);
    expect(container.textContent).toBe("Number hidden Transf a Name hidden ID number hidden");
    expect(container.textContent).not.toContain("[");
  });

  it("leaves text without placeholders untouched", () => {
    const { container } = render(<RedactedText text="Compra Nacional MD JUMBO CONCEPCION" />);
    expect(chips(container)).toEqual([]);
    expect(container.textContent).toBe("Compra Nacional MD JUMBO CONCEPCION");
  });

  it("leaves unknown or malformed codes as plain text", () => {
    const text = "[SECRET] [person] [PERS [ PERSON ] PERSON";
    const { container } = render(<RedactedText text={text} />);
    expect(chips(container)).toEqual([]);
    expect(container.textContent).toBe(text);
  });

  it("never turns the text into markup", () => {
    const { container } = render(<RedactedText text="<b>JUMBO</b> [EMAIL]" />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe("<b>JUMBO</b> Email hidden");
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <p>
        <RedactedText text="TEF DE [PERSON] [EMAIL] [PHONE] [ADDRESS]" />
      </p>,
    );
    expect((await axe(container)).violations).toEqual([]);
  });
});

describe("placeholder codes", () => {
  it("every code in the contract has an English label that says it is hidden", () => {
    expect(PLACEHOLDERS).toEqual(["PERSON", "ID", "NUMBER", "EMAIL", "PHONE", "ADDRESS"]);
    for (const code of PLACEHOLDERS) {
      const label = tDynamic("redaction", code);
      expect(label).not.toBe(code);
      expect(label).toMatch(/ hidden$/);
    }
  });

  it("splits text into parts in order", () => {
    expect(splitPlaceholders("Transf a [PERSON] [ID]")).toEqual([{ text: "Transf a " }, { code: "PERSON" }, { text: " " }, { code: "ID" }]);
    expect(splitPlaceholders("")).toEqual([]);
  });

  it("gives a translated plain-text version for tooltips", () => {
    expect(redactedPlainText("Transf a [PERSON]")).toBe("Transf a [Name hidden]");
    expect(redactedPlainText("JUMBO")).toBe("JUMBO");
  });
});
