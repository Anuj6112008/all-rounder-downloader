// Playwright config: mobile 390x844 + desktop 1440x900 projects.
// BASE_URL env targets production; defaults to the local server.
const { defineConfig } = require("@playwright/test");

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8000";

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "mobile",
      use: { browserName: "chromium", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
    {
      name: "desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: "python run.py",
        url: "http://127.0.0.1:8000/api/health",
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
