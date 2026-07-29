import { test, expect } from "@playwright/test";

// The RNS feed can legitimately be empty on a quiet weekend, so a passing run
// means the page resolved to EITHER the feed table or an explicit empty state
// (not a stuck spinner or a crash).
test("rns feed resolves", async ({ page }) => {
  await page.goto("/rns");

  const table = page.getByRole("table");
  const empty = page.getByText(/No announcements/i);
  await expect(table.or(empty).first()).toBeVisible({ timeout: 20_000 });
});

// The filter controls are React state on a route that unmounts on navigation, so
// without the sessionStorage round-trip they snap back to 24h / AI 50 every time
// the user leaves and returns. Identify the selects by an option only each one
// has — neither is wired to a <label for>, so there's no accessible name to use.
test("rns filters survive leaving the page and coming back", async ({ page }) => {
  await page.goto("/rns");

  const windowSelect = page
    .locator("select")
    .filter({ has: page.locator('option[value="168"]') });
  const capSelect = page
    .locator("select")
    .filter({ has: page.locator('option[value="1000000000"]') });
  const score = page.locator('input[type="range"]');

  await expect(windowSelect).toBeVisible({ timeout: 20_000 });
  await windowSelect.selectOption("168");
  await capSelect.selectOption("1000000000");
  await score.fill("75");

  await page.goto("/screener");
  await expect(page).toHaveURL(/\/screener/);
  await page.goto("/rns");

  await expect(windowSelect).toHaveValue("168", { timeout: 20_000 });
  await expect(capSelect).toHaveValue("1000000000");
  await expect(score).toHaveValue("75");
});
