import { defineConfig, devices } from "@playwright/test";
import { DOSSIER_COURRIELS, RACINE_BACKEND } from "./e2e-integration/dossiers.cjs";

/**
 * Tests de bout en bout AVEC le vrai backend (tâche T5) : Django (gunicorn) + PostgreSQL + Redis,
 * le frontend de production (`next start`) et un petit proxy qui joue le rôle de Caddy
 * (`/api/*` vers Django, le reste vers Next.js, même origine). Aucune route n'est simulée.
 *
 * À lancer avec `npm run test:e2e:integration` : le script prépare d'abord la base et les comptes
 * (`e2e-integration/preparer.mjs`), puis Playwright démarre les trois serveurs. Il faut un build
 * (`npm run build`) et l'environnement du backend (voir docs/tests.md, section 7).
 *
 * Les tests s'enchaînent dans un seul processus : ils partagent la même base.
 */
const PORT = Number(process.env.E2E_INT_PORT ?? 3123);
const PORT_NEXT = Number(process.env.E2E_INT_PORT_NEXT ?? PORT + 1);
const PORT_BACKEND = Number(process.env.E2E_INT_PORT_BACKEND ?? 8123);
const ORIGINE = `http://localhost:${PORT}`;
const python = process.env.ALPHA_E2E_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e-integration",
  testMatch: /.*\.spec\.ts/,
  outputDir: "./test-results-integration",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never", outputFolder: "playwright-report-integration" }]] : [["list"]],
  use: {
    baseURL: ORIGINE,
    locale: "fr-FR",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: process.env.CI ? "retain-on-failure" : "off",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Django derrière gunicorn, réglages config.settings.e2e (e-mails dans un dossier, Celery immédiat).
      command: `${python} -m gunicorn config.wsgi:application --bind 127.0.0.1:${PORT_BACKEND} --workers 2 --threads 2 --access-logfile - --error-logfile -`,
      cwd: RACINE_BACKEND,
      env: {
        DJANGO_SETTINGS_MODULE: "config.settings.e2e",
        ALPHA_E2E_DOSSIER_EMAILS: DOSSIER_COURRIELS,
        ALPHA_URL_FRONTEND: ORIGINE,
        DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1",
      },
      url: `http://127.0.0.1:${PORT_BACKEND}/api/v1/auth/csrf`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx next start -p ${PORT_NEXT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${PORT_NEXT}/connexion`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "node e2e-integration/proxy.mjs",
      env: {
        PROXY_PORT: String(PORT),
        PROXY_BACKEND: `http://127.0.0.1:${PORT_BACKEND}`,
        PROXY_FRONTEND: `http://127.0.0.1:${PORT_NEXT}`,
      },
      url: `${ORIGINE}/connexion`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
