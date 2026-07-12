import { test, expect } from "@playwright/test";

// The primary app nav (AppShell) renders on every non-landing page. This checks
// the nav is present, routes between top-level pages, and that no page loads
// with an uncaught JS exception.
test("primary nav routes between pages", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));

  await page.goto("/screener");

  const nav = page.locator("nav").first();
  await expect(nav.getByRole("link", { name: "Screener" }).first()).toBeVisible();

  await nav.getByRole("link", { name: "Markets", exact: true }).first().click();
  await expect(page).toHaveURL(/\/markets/);

  await page
    .locator("nav")
    .first()
    .getByRole("link", { name: "Research", exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(/\/research/);

  expect(pageErrors, `uncaught page errors: ${pageErrors.join("; ")}`).toHaveLength(0);
});
