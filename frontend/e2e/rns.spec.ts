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
