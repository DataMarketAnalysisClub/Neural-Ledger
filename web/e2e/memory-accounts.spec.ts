import { expect, test } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

test.use({ trace: "off" });

/**
 * ADR-048, saved only, on the real accounts backend: consent in the profile, a salary said in chat, the memory card,
 * then the profile's view, a new version, the export and the deletion. Every amount is synthetic, the account is
 * new, and nothing here moves money or changes a projection.
 */
const PASSWORD = "synthetic-passphrase-123";
// Eight synthetic monthly cartolas (`neural-ledger cartola --months 8 --seed 21 --month 2026-09 --salary 1100000`), so
// the account has its own financial model and the copilot opens. Fictional holder; never a real statement.
const HISTORY = fileURLToPath(new URL("./fixtures/memory-history/", import.meta.url));

test("a user turns memory on, confirms a salary from chat, edits, exports and deletes it", async ({ page, request }) => {
  const health = await request.get("/api/health");
  test.skip(!health.ok() || (await health.json()).auth !== "accounts", "Accounts backend is not enabled in this stack");
  const identityHeaders: string[] = [];
  page.on("request", (sent) => {
    if (new URL(sent.url()).pathname.startsWith("/api/") && sent.headers()["x-user-id"] !== undefined) identityHeaders.push(sent.url());
  });

  await page.goto("/signup");
  await page.getByLabel("Display name").fill("Memory Tester");
  await page.getByLabel("Email").fill(`memory-${crypto.randomUUID()}@example.invalid`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("checkbox", { name: /I understand this is a sandbox/ }).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByRole("link", { name: "Later" }).click();
  const origin = new URL(page.url()).origin;
  for (const name of readdirSync(HISTORY).filter((file) => file.endsWith(".xlsx")).sort()) {
    // The page's own context: its HttpOnly session cookie, and the app's Origin, as the Statements page sends it.
    const imported = await page.request.post("/api/v1/statements", { data: readFileSync(HISTORY + name), headers: { Origin: origin, "Content-Type": "application/octet-stream" } });
    expect(imported.status()).toBe(200);
  }
  await page.reload();

  // Without consent the copilot prepares nothing.
  await page.goto("/copilot");
  await page.getByLabel("Ask about your money").fill("Mi sueldo líquido es 1.234.567 desde noviembre");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/I need your permission first/)).toBeVisible();
  await expect(page.getByRole("form", { name: "Salary to remember" })).toHaveCount(0);

  // Consent in the profile.
  await page.goto("/profile");
  const memory = page.locator("#memory");
  await expect(memory.getByText("Memory was never turned on")).toBeVisible();
  await memory.getByRole("button", { name: "Turn memory on" }).click();
  await expect(memory.getByText("Memory is on")).toBeVisible();

  // The card: prepared from the message, saved only when the user confirms.
  await page.goto("/copilot");
  await page.getByLabel("Ask about your money").fill("Mi sueldo líquido es 1.234.567 desde noviembre");
  await page.getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("form", { name: "Salary to remember" });
  await expect(card).toContainText("CLP 1,234,567");
  await expect(card).toContainText("it moves no money and does not change your projections");
  const [confirmed] = await Promise.all([
    page.waitForResponse((r) => /\/api\/v1\/memory\/proposals\/[^/]+\/confirm$/.test(new URL(r.url()).pathname)),
    card.getByRole("button", { name: "Save salary" }).click(),
  ]);
  expect(confirmed.status()).toBe(200);
  await expect(card.getByRole("status")).toContainText("does not change your projections");
  await expect(card.getByRole("button", { name: "Save salary" })).toHaveCount(0);  // no second confirmation

  // The profile shows it, edits it as a new version, exports and deletes it.
  await page.goto("/profile");
  await expect(memory.getByText("CLP 1,234,567")).toBeVisible();
  await expect(memory.getByText("1 versions kept")).toBeVisible();
  await memory.getByRole("button", { name: "Change salary" }).click();
  await memory.getByLabel("Net salary (CLP)").fill("1300000");
  await memory.getByLabel("From the pay month").fill("2026-12");
  await memory.getByRole("button", { name: "Save salary" }).click();
  await expect(memory.getByText(/Saved as a new version/)).toBeVisible();
  await expect(memory.getByText("2 versions kept")).toBeVisible();

  const [download] = await Promise.all([page.waitForEvent("download"), memory.getByRole("button", { name: "Export my memory" }).click()]);
  expect(download.suggestedFilename()).toBe("neural-ledger-memory.json");
  await expect(memory.getByText("Downloaded 2 versions.")).toBeVisible();

  await memory.getByRole("button", { name: "Delete my salary" }).click();
  await memory.getByRole("button", { name: "Delete every version" }).click();
  await expect(memory.getByText("Deleted 2 versions.")).toBeVisible();
  await expect(memory.getByText("You have not declared a salary.")).toBeVisible();
  expect(identityHeaders).toEqual([]);  // the session cookie only, never an identity header
});
