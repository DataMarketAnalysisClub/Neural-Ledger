import { expect, test } from "@playwright/test";

test.use({ trace: "off" });

test("accounts signup can be deferred, and signout returns to the public entry", async ({ page, request }) => {
  const health = await request.get("/api/health");
  test.skip(!health.ok() || (await health.json()).auth !== "accounts", "Accounts backend is not enabled in this stack");

  await page.goto("/signup");
  await page.getByLabel("Display name").fill("Synthetic Tester");
  await page.getByLabel("Email").fill(`browser-${crypto.randomUUID()}@example.invalid`);
  await page.getByLabel("Password").fill("synthetic-passphrase-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your saving preferences" })).toBeVisible();
  await page.getByRole("link", { name: "Later" }).click();
  await expect(page.getByText("No financial data yet").first()).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
