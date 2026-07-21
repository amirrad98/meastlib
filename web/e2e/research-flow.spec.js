import { expect, test } from "@playwright/test";

const itemId = process.env.MEASTLIB_E2E_ITEM_ID;
const query = process.env.MEASTLIB_E2E_QUERY;

test("a reader can discover a work without a query", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Recently added" })).toBeVisible();
  const cards = page.locator(".catalog-card");
  await expect(cards.first()).toBeVisible();
});

test("bookmarked searches restore results", async ({ page }) => {
  test.skip(!query, "Set MEASTLIB_E2E_QUERY for a populated local corpus");
  await page.goto(`/search?q=${encodeURIComponent(query)}`);
  await expect(page.locator(".work-hit").first()).toBeVisible();
});

test("a search hit produces a visible scan overlay", async ({ page }) => {
  test.skip(!query || !itemId, "Set MEASTLIB_E2E_QUERY and MEASTLIB_E2E_ITEM_ID");
  await page.goto(`/search?q=${encodeURIComponent(query)}`);
  const pageHit = page.locator(`.page-hit[href*="/item/${itemId}/"]`).first();
  await expect(pageHit).toBeVisible();
  await pageHit.click();
  await expect(page.locator(".ocr-highlight-overlay").first()).toBeVisible({ timeout: 15_000 });
});
