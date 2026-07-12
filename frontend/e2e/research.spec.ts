import { test, expect } from "@playwright/test";

// The research blog is server-rendered with a post list. Opening the first post
// checks both the list and the /research/[slug] detail route.
test("research list opens a post", async ({ page }) => {
  await page.goto("/research");

  // Post links are /research/<slug>; exclude the admin editor link.
  const posts = page.locator('a[href^="/research/"]:not([href="/research/admin"])');
  await expect(posts.first()).toBeVisible();

  await posts.first().click();
  await expect(page).toHaveURL(/\/research\/.+/);
  await expect(page.getByRole("heading").first()).toBeVisible();
});
