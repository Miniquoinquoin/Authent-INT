import { defineConfig, devices } from '@playwright/test'

/**
 * E2E against the mock: the Vite dev server in mock mode, MSW in the browser (ADR §17, B5
 * "Fini quand: parcours Playwright vert contre le mock"). Port 5174 to stay clear of the
 * dev stack (Caddy on 443) and of a plain `npm run dev` on 5173.
 */
const PORT = 5174

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev:mock -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
