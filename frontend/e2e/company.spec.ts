import { test, expect } from "@playwright/test";

// AZN.L exercises the dot-in-path company route. The SEO <h1> is server-
// rendered, so it must be in the initial HTML regardless of client hydration.
test("company page loads for AZN.L", async ({ page }) => {
  await page.goto("/company/AZN.L");

  await expect(
    page.getByRole("heading", { name: /astrazeneca/i }).first()
  ).toBeVisible();
});
