import { expect, test } from "@playwright/test";

test.use({ trace: "off" });

test("accounts signup can be deferred, stays empty without a sample action, and signout returns to the public entry", async ({ page, request }) => {
  const health = await request.get("/api/health");
  test.skip(!health.ok() || (await health.json()).auth !== "accounts", "Accounts backend is not enabled in this stack");
  const sampleRequests: string[] = [];
  page.on("request", (sent) => { if (/sample/i.test(new URL(sent.url()).pathname)) sampleRequests.push(sent.url()); });
  const email = `browser-${crypto.randomUUID()}@example.invalid`;
  const password = "synthetic-passphrase-123";

  await page.goto("/signup");
  await page.getByLabel("Display name").fill("Synthetic Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your saving preferences" })).toBeVisible();
  await page.getByRole("link", { name: "Later" }).click();
  await expect(page.getByText("No financial data yet").first()).toBeVisible();
  await expect(page.getByText("Capacity is unavailable until financial data is available. No permitted profile can be shown yet.")).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(0);
  await expect(page.getByText(/sample/i)).toHaveCount(0);

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("No financial data yet");
  await expect(page.getByRole("link", { name: "Open profile" })).toBeVisible();
  await expect(page.getByText(/CLP/)).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("No financial data yet");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(sampleRequests).toEqual([]);
});

test("a demo persona enters read only and keeps its own figures (E01)", async ({ page, request }) => {
  const health = await request.get("/api/health");
  const info = (health.ok() ? await health.json() : {}) as { readonly auth?: string; readonly demo_personas?: readonly string[] };
  test.skip(info.auth !== "accounts" || !(info.demo_personas ?? []).includes("camila"), "Accounts backend with demo personas is not enabled in this stack");

  await page.goto("/signin");
  await page.getByRole("button", { name: "Explore as Camila" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("December 2026: CLP 20,000 protected of CLP 920,000");

  await page.getByRole("link", { name: "Profile" }).first().click();
  await expect(page.getByText("This synthetic demo profile is read only.")).toBeVisible();
  await expect(page.getByLabel("Display name")).toHaveCount(0);
  await expect(page.getByText("No financial data yet")).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
