import { expect, test, type Page } from "@playwright/test";

/** The session_id the next chat request sends, read from the network. */
async function nextChatSession(page: Page, send: () => Promise<void>): Promise<string> {
  const request = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && r.method() === "POST");
  await send();
  return ((await request).postDataJSON() as { session_id: string }).session_id;
}

test("New conversation sends a new session_id, empties the log and scopes the audit trail", async ({ page }) => {
  await page.goto("/copilot");
  const log = page.getByRole("log");
  const ask = () => page.getByRole("button", { name: "Will I be OK in December?" }).click();

  const first = await nextChatSession(page, ask);
  await expect(log.locator("li")).toHaveCount(2, { timeout: 30_000 }); // question and reply

  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(log).not.toContainText("Will I be OK in December?");
  const second = await nextChatSession(page, ask);
  expect(second).not.toBe(first);
  await expect(log.locator("li")).toHaveCount(2, { timeout: 30_000 });

  await page.getByRole("link", { name: "Audit trail" }).click();
  const rows = page.getByRole("table").locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const all = await rows.count();
  await page.getByLabel("Conversation").selectOption("session");
  await expect.poll(() => rows.count()).toBeLessThan(all); // only the second conversation's events
  expect(await rows.count()).toBeGreaterThan(0);
});

test("the profile is read only and shows the declared tolerance", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Profile");
  await expect(page.getByText("Aggressive")).toBeVisible();
  await expect(page.getByText(/Not answered yet \(pq-0\.1, 5 questions\)/)).toBeVisible();
  await page.getByRole("radio", { name: /Diego/ }).check({ force: true });
  await expect(page.getByText("Moderate")).toBeVisible();
});
