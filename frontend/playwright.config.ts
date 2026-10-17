import { defineConfig } from "@playwright/test";

// Drives the real UI in a real browser against the real API and a scratch copy of the demo database.
// Run it with `npm run e2e` (which creates and drops that copy); it uses Google Chrome as installed.
// E2E_BASE_URL points the suite at an already-running stack (e.g. the containers on http://127.0.0.1:5173) instead of
// starting its own API and dev server against a scratch copy of the demo database.
const external = process.env.E2E_BASE_URL;
// The suite runs its own API and UI on ports of its own, so it never collides with (or reaches) a demo you have running
// on 8000/5173. Override with PULSE_E2E_API_PORT / PULSE_E2E_UI_PORT.
const apiPort = process.env.PULSE_E2E_API_PORT ?? "8100";
const uiPort = process.env.PULSE_E2E_UI_PORT ?? "8173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: external ?? `http://127.0.0.1:${uiPort}`, channel: "chrome", headless: true, screenshot: "only-on-failure" },
  webServer: external ? undefined : [
    { command: "bash ../infra/scripts/e2e_api.sh", url: `http://127.0.0.1:${apiPort}/openapi.json`, reuseExistingServer: false, timeout: 60_000 },
    { command: `npm run dev -- --host 127.0.0.1 --port ${uiPort} --strictPort`, url: `http://127.0.0.1:${uiPort}`, reuseExistingServer: false, env: { PULSE_API_PORT: apiPort }, timeout: 60_000 },
  ],
});
