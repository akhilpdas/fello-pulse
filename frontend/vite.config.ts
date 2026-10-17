/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API port is 8000 unless the browser tests (which run their own API) say otherwise.
const apiPort = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.PULSE_API_PORT ?? "8000";

// The browser only talks to this origin; /api is proxied to the FastAPI app, so
// there is no CORS surface to configure or get wrong.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
