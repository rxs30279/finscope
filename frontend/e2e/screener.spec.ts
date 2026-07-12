import { test, expect } from "@playwright/test";

// The screener is always populated (500+ UK listings), so a real render must
// produce a table with many data rows.
test("screener renders a populated table", async ({ page }) => {
  await page.goto("/screener");

  await expect(page.getByRole("table")).toBeVisible();

  // Rows hydrate after the /api/screener fetch resolves.
  await expect(async () => {
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeGreaterThan(10);
  }).toPass({ timeout: 20_000 });
});
