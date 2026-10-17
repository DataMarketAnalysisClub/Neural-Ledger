import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

test.use({ trace: "off" });

/**
 * Statement import on the real accounts backend, with the synthetic Santander export (never a real cartola). Each
 * account reads and imports through its own HttpOnly session cookie; nothing crosses to another account, and an
 * import adds no projection and changes no profile. Every account here is new, so the first import is never a duplicate.
 */
const SAMPLE = fileURLToPath(new URL("./fixtures/synthetic-santander.xlsx", import.meta.url));
const PASSWORD = "synthetic-passphrase-123";

async function signUp(page: Page, name: string, email: string) {
  await page.getByLabel("Display name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your saving preferences" })).toBeVisible();
  await page.getByRole("link", { name: "Later" }).click();
}

async function openStatements(page: Page) {
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Statements" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Statements");
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

test("each account imports and reads only its own statements, and an import unlocks no projection", async ({ page, request }) => {
  const health = await request.get("/api/health");
  test.skip(!health.ok() || (await health.json()).auth !== "accounts", "Accounts backend is not enabled in this stack");
  const identityHeaders: string[] = [];
  page.on("request", (sent) => {
    if (new URL(sent.url()).pathname.startsWith("/api/") && sent.headers()["x-user-id"] !== undefined) identityHeaders.push(sent.url());
  });
  const first = `statements-a-${crypto.randomUUID()}@example.invalid`;
  const second = `statements-b-${crypto.randomUUID()}@example.invalid`;

  // First account: an empty account still reaches its own statements, told they build the ledger only.
  await page.goto("/signup");
  await signUp(page, "Statement Owner", first);
  await openStatements(page);
  await expect(page.getByText(/build this account's transaction ledger only\. They add no projections/)).toBeVisible();
  await expect(page.getByText(/still use the demo scenario/)).toHaveCount(0);
  await expect(page.getByText("No statements imported yet.")).toBeVisible();

  const [upload] = await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/statements" && r.request().method() === "POST"),
    page.getByLabel("Choose file").setInputFiles(SAMPLE),
  ]);
  expect(upload.status()).toBe(200);
  const imported = (await upload.json()) as { data: { imports: { duplicate: boolean; statement: { statement_id: string } }[] } };
  expect(imported.data.imports.length).toBeGreaterThan(0);
  expect(imported.data.imports.every((item) => !item.duplicate)).toBe(true);
  const statementId = imported.data.imports[0]!.statement.statement_id;
  await expect(page.getByRole("heading", { name: "Imported synthetic-santander.xlsx" })).toBeVisible();
  await expect(page.getByText(/transactions in the ledger/)).toBeVisible();

  await page.getByRole("button", { name: /Open statement for \*\*\*\*3456/ }).click();
  await expect(page.getByRole("heading", { level: 2, name: /\*\*\*\*3456/ })).toBeVisible();
  await expect(page.locator("[data-placeholder='PERSON']").first()).toBeVisible();
  await expect(page.getByText("[PERSON]")).toHaveCount(0);
  await page.getByRole("radio", { name: "Transactions" }).check({ force: true });
  await expect(page.getByRole("table", { name: "Transactions from imported statements" })).toContainText("CLP −900");

  // The import changed neither the account's data source nor its stored tolerance, and no forecast appeared.
  expect(await (await page.request.get("/api/v1/me")).json()).toMatchObject({ data_source: "empty" });
  expect(await (await page.request.get("/api/v1/profile")).json()).toMatchObject({ data: { declared_tolerance: null } });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("No financial data yet");
  await expect(page.getByText(/CLP/)).toHaveCount(0);

  // Second account, in the same tab without a reload: nothing of the first account's import or ledger remains.
  await signOut(page);
  await page.getByRole("link", { name: "Create an account" }).click();
  await signUp(page, "Second Owner", second);
  await openStatements(page);
  await expect(page.getByText("No statements imported yet.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Imported synthetic-santander.xlsx" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Open statement for/ })).toHaveCount(0);
  await page.getByRole("radio", { name: "Transactions" }).check({ force: true });
  await expect(page.getByText("No transactions yet.")).toBeVisible();
  const foreign = await page.request.get(`/api/v1/statements/${encodeURIComponent(statementId)}`);
  expect(foreign.status()).not.toBe(200);
  expect(await foreign.text()).not.toContain("****3456");

  // Back as the first account: its statement is still there.
  await signOut(page);
  await page.getByLabel("Email").fill(first);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("No financial data yet");
  await openStatements(page);
  await expect(page.getByRole("button", { name: /Open statement for \*\*\*\*3456/ })).toBeVisible();
  await signOut(page);

  expect(identityHeaders).toEqual([]);
});
