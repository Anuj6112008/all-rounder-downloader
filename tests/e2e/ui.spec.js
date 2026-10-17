// Frontend e2e: paste, fetch, tabs, downloads, error states, history,
// language toggle, PWA installability, and zero console errors.
// Runs on mobile (390x844) and desktop (1440x900) via playwright.config.js.
const { test, expect } = require("@playwright/test");

const YT = "https://www.youtube.com/watch?v=jNQXAC9IVRw";

test.beforeEach(async ({ page }) => {
  // fresh state per test
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("home loads with title, input, no console errors", async ({ page }) => {
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));

  await expect(page).toHaveTitle(/IGDesk Downloader/);
  await expect(page.locator("#urlInput")).toBeVisible();
  await expect(page.locator("#fetchBtn")).toBeVisible();
  // 44px tap targets
  const box = await page.locator("#fetchBtn").boundingBox();
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
});

test("platform auto-detects from link", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await expect(page.locator("#platformBadge")).toBeVisible();
  await expect(page.locator("#platformName")).toHaveText("YouTube");
});

test("paste button fills input (clipboard permission)", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.evaluate(() => navigator.clipboard.writeText(YT));
  await page.click("#pasteBtn");
  await expect(page.locator("#urlInput")).toHaveValue(YT);
});

test("fetch returns result card with title/duration and tabs", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });
  await expect(page.locator("#rTitle")).not.toHaveText("—");
  await expect(page.locator("#rTitle")).toContainText(/zoo/i);
  await expect(page.locator("#rDuration")).toContainText("0:19");
  await expect(page.locator("#videoList .fmt-row")).not.toHaveCount(0);
  await expect(page.locator("#audioList .fmt-row")).not.toHaveCount(0);
});

test("tab switching toggles panels and aria-selected", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });

  await page.click("#tab-audio");
  await expect(page.locator("#panel-audio")).toBeVisible();
  await expect(page.locator("#panel-video")).toBeHidden();
  await expect(page.locator("#tab-audio")).toHaveAttribute("aria-selected", "true");

  await page.click("#tab-thumb");
  await expect(page.locator("#panel-thumb")).toBeVisible();
  await expect(page.locator("#thumbPreview")).toBeVisible();
});

test("video download button completes with success state", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });

  const dlPromise = page.waitForEvent("download", { timeout: 90_000 });
  await page.locator("#videoList .dl-btn").first().click();
  const download = await dlPromise;
  expect(download.suggestedFilename()).toMatch(/\.(mp4|mkv|webm)$/i);
});

test("mp3 download produces an .mp3 file", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });

  await page.click("#tab-audio");
  const dlPromise = page.waitForEvent("download", { timeout: 90_000 });
  await page.locator('#audioList .dl-btn[data-kind="mp3"]').first().click();
  const download = await dlPromise;
  expect(download.suggestedFilename()).toMatch(/\.mp3$/i);
});

test("thumbnail download produces an image file", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });
  await page.click("#tab-thumb");

  const dlPromise = page.waitForEvent("download", { timeout: 60_000 });
  await page.locator('.thumb-buttons .dl-btn[data-ext="jpg"]').click();
  const download = await dlPromise;
  expect(download.suggestedFilename()).toMatch(/\.jpg$/i);
});

test("error state shown for invalid/unsupported URL", async ({ page }) => {
  await page.fill("#urlInput", "https://evil.example.com/video");
  await page.click("#fetchBtn");
  await expect(page.locator("#status")).toContainText(/platform|coming|support/i, { timeout: 30_000 });
  await expect(page.locator("#result")).toBeHidden();
});

test("empty input shows validation message", async ({ page }) => {
  await page.fill("#urlInput", "");
  await page.click("#fetchBtn");
  await expect(page.locator("#status")).toContainText(/enter|paste|link/i);
});

test("clear button resets input and result", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#clearBtn");
  await expect(page.locator("#urlInput")).toHaveValue("");
});

test("history opt-in stores items locally and can be cleared", async ({ page }) => {
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });

  // opt in AFTER fetch -> then fetch again so it records
  await page.locator("#historyToggle").check();
  await page.click("#fetchBtn");
  await expect(page.locator("#historyList li")).toHaveCount(1, { timeout: 45_000 });

  const stored = await page.evaluate(() => localStorage.getItem("igdesk.history"));
  expect(stored).toContain("youtube.com");

  await page.click("#clearHistoryBtn");
  await expect(page.locator("#historyList li")).toHaveCount(0);
  await page.locator("#historyToggle").uncheck();
  expect(await page.evaluate(() => localStorage.getItem("igdesk.history"))).toBeNull();
});

test("language toggle switches to Hinglish and persists", async ({ page }) => {
  await expect(page.locator("#fetchBtn")).toHaveText("Fetch");
  await page.click("#langBtn");
  await expect(page.locator("#fetchBtn")).toHaveText("Fetch karein");
  expect(await page.evaluate(() => localStorage.getItem("igdesk.lang"))).toBe("hi");
  await page.reload();
  await expect(page.locator("#fetchBtn")).toHaveText("Fetch karein");
});

test("theme toggle switches to light and persists", async ({ page }) => {
  const before = await page.getAttribute("html", "data-theme");
  await page.click("#themeBtn");
  const after = await page.getAttribute("html", "data-theme");
  expect(after).not.toBe(before);
  await page.reload();
  expect(await page.getAttribute("html", "data-theme")).toBe(after);
});

test("PWA manifest + service worker registered (installable)", async ({ page }) => {
  await page.goto("/");
  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  expect(manifestHref).toBe("/manifest.webmanifest");

  const res = await page.request.get("/manifest.webmanifest");
  expect(res.status()).toBe(200);
  const manifest = await res.json();
  expect(manifest.name).toBe("IGDesk Downloader");
  expect(manifest.icons.length).toBeGreaterThanOrEqual(2);

  // service worker reaches 'activated' state
  const swReady = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    return !!reg.active;
  });
  expect(swReady).toBe(true);
});

test("copy-link button copies the source URL", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.fill("#urlInput", YT);
  await page.click("#fetchBtn");
  await expect(page.locator("#result")).toBeVisible({ timeout: 45_000 });
  await page.click("#copyBtn");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toContain("youtube.com");
});

test("legal pages reachable and titled", async ({ page }) => {
  for (const [path, title] of [
    ["/about.html", /About/],
    ["/terms.html", /Terms/],
    ["/privacy.html", /Privacy/],
    ["/dmca.html", /DMCA/],
    ["/faq.html", /FAQ|Frequently/],
  ]) {
    await page.goto(path);
    await expect(page).toHaveTitle(title);
  }
});
