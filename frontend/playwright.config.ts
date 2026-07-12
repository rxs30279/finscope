import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke journeys against the live production frontend. No local
// build or dev server — these double as user-perspective monitoring. Override
// the target with E2E_BASE_URL (e.g. http://localhost:3000 against `npm run dev`).
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://app.alphamoveai.co.uk",
    trace: "on-first-retry",
    actionTimeout: 15_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
