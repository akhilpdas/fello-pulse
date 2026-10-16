import { defineConfig } from "@playwright/test";

// Drives the real UI in a real browser against the real API and a scratch copy of the demo database.
// Run it with `npm run e2e` (which creates and drops that copy); it uses Google Chrome as installed.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5173", channel: "chrome", headless: true, screenshot: "only-on-failure" },
  webServer: [
    { command: "bash ../infra/scripts/e2e_api.sh", url: "http://127.0.0.1:8000/openapi.json", reuseExistingServer: false, timeout: 60_000 },
    { command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort", url: "http://127.0.0.1:5173", reuseExistingServer: true, timeout: 60_000 },
  ],
});
