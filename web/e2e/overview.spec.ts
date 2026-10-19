import { expect, test, type Page } from "@playwright/test";

/** On a phone the app opens on the Copilot, so the Overview is one tap on the bottom bar; on a wide screen "/" is it. */
async function openOverview(page: Page) {
  await page.goto("/");
  const phoneTab = page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Overview" });
  if (await phoneTab.isVisible()) await phoneTab.click();
}

/**
 * Scene 1 (E01): the numbers on screen are the engine's golden answers, read from the DOM.
 * If the UI ever recomputed money, these would drift.
 */
test.describe("Overview", () => {
  test("Camila: December is the binding month with CLP 20,000 protected (E01)", async ({ page }) => {
    await openOverview(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("December 2026: CLP 20,000 protected of CLP 920,000");
    const bridge = page.getByRole("figure", { name: /protected surplus/i });
    await expect(bridge).toContainText("CLP 170,000"); // lowest conservative balance before payday
    await expect(bridge).toContainText("CLP 150,000"); // safety floor
    await expect(page.getByText("CLP 20,000 above the floor")).toBeVisible();
  });

  test("Diego: same balances, a shortfall instead of a surplus", async ({ page }) => {
    await openOverview(page);
    await page.getByRole("radio", { name: /Diego/ }).check({ force: true });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("April 2027: CLP 1,940,000 below the safety floor");
    await expect(page.getByRole("figure", { name: /shortfall/i })).toContainText("CLP −1,790,000");
  });

  test("every amount carries its currency code and the persona switch clears data", async ({ page }) => {
    await openOverview(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("CLP");
    await page.getByRole("radio", { name: /Diego/ }).check({ force: true });
    await expect(page.getByRole("heading", { level: 1 })).not.toContainText("protected of");
  });
});
