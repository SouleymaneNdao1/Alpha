import { defineConfig, devices } from "@playwright/test";

/**
 * Tests E2E de l'interface : l'API est simulée avec `page.route`, aucun
 * backend n'est nécessaire. À lancer sur le build de production
 * (`npm run build`, puis `npm run test:e2e` qui démarre `next start`).
 */
const PORT = Number(process.env.E2E_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: "fr-FR",
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}/connexion`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
