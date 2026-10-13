import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end demo arc against a running stack (docker compose up, or `make api` + `npm run dev`).
 * BASE_URL defaults to the compose web service. Uses the installed Chrome locally; CI can set
 * PW_CHANNEL="" to use Playwright's bundled Chromium.
 */
const channel = process.env.PW_CHANNEL ?? "chrome";
const withChannel = channel ? { channel } : {};

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, ...withChannel } },
    { name: "mobile", use: { ...devices["Pixel 7"], ...withChannel }, testMatch: /overview/ },
  ],
});
