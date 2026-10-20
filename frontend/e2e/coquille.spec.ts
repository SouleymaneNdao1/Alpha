import { expect, test } from "@playwright/test";
import { erreur, json, ouvrirSession, simulerApi } from "./aide";
import { COMPTEURS, MOI_COMPLET, MOI_SUPER_ADMIN, moiAvec, ouvrirEtSimuler, page as pageDe } from "./donnees";

const menu = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "Navigation principale" });
const vide = (_a: unknown, route: Parameters<typeof json>[0]) => json(route, pageDe([]));

test.describe("Coquille de l'application (F2)", () => {
  test("menu limité aux modules et permissions de Moi : compte seul", async ({ page }) => {
    await ouvrirEtSimuler(page, moiAvec({ modules: ["COMPTE"], permissions: [] }), { "GET /taches": vide });
    await page.goto("/a-traiter");
    await expect(menu(page).getByRole("link", { name: /À traiter/ })).toBeVisible();
    await expect(menu(page).getByRole("link", { name: "Mon compte" })).toBeVisible();
    await expect(menu(page).getByRole("link", { name: "Administration" })).toHaveCount(0);
    await expect(menu(page).getByRole("link", { name: "Journal d'audit" })).toHaveCount(0);
    await expect(page.getByLabel("Barre latérale").getByText("Gestion interne")).toBeVisible();
    await expect(page.getByText("Suivi et traçabilité")).toHaveCount(0);
  });

  test("menu complet : administration et journal, avec compteur sur « À traiter »", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, { "GET /taches": vide });
    await page.goto("/a-traiter");
    for (const nom of ["Administration", "Journal d'audit", "Mon compte"]) {
      await expect(menu(page).getByRole("link", { name: nom })).toBeVisible();
    }
    await expect(menu(page).getByRole("link", { name: /À traiter/ })).toContainText(String(COMPTEURS.total));
    await expect(menu(page).getByRole("link", { name: /À traiter/ })).toHaveAttribute("aria-current", "page");
    await menu(page).getByRole("link", { name: "Administration" }).click();
    await expect(page).toHaveURL(/\/administration\/utilisateurs$/);
    await expect(page.getByRole("heading", { name: "Utilisateurs et rôles" })).toBeVisible();
  });

  test("un module sans permission (ou l'inverse) n'ouvre aucune entrée", async ({ page }) => {
    await ouvrirEtSimuler(page, moiAvec({ modules: ["COMPTE", "AUDIT"], permissions: ["admin.utilisateurs"] }), { "GET /taches": vide });
    await page.goto("/a-traiter");
    await expect(menu(page).getByRole("link", { name: "Journal d'audit" })).toHaveCount(0);
    await expect(menu(page).getByRole("link", { name: "Administration" })).toHaveCount(0);
  });

  test("super-admin : pas de Mon compte ni d'administration, message explicatif", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_SUPER_ADMIN);
    await page.goto("/a-traiter");
    await expect(page.getByText(/n'est rattaché à aucun établissement/)).toBeVisible();
    await expect(menu(page).getByRole("link", { name: "Mon compte" })).toHaveCount(0);
    await expect(menu(page).getByRole("link", { name: "Administration" })).toHaveCount(0);
  });

  test("cloche : compteur des notifications non lues", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": vide,
      "GET /moi/notifications": (_a, route) => json(route, { ...pageDe([]), non_lues: 4 }),
    });
    await page.goto("/a-traiter");
    await expect(page.getByTestId("compteur-cloche")).toHaveText("4");
    await expect(page.getByRole("button", { name: "Notifications : 4 non lues" })).toBeVisible();
  });

  test("session expirée : retour à la connexion avec la route demandée", async ({ page }) => {
    await ouvrirSession(page);
    await simulerApi(page, { "GET /auth/session": (_a, route) => erreur(route, 401, "SESSION_EXPIREE", "Session expirée.") });
    await page.goto("/journal");
    await expect(page).toHaveURL(/\/connexion\?suivant=%2Fjournal&motif=expiree/);
  });

  test("avertissement d'inactivité, « Rester connecté » puis expiration", async ({ page }) => {
    await page.clock.install();
    const appels = await ouvrirEtSimuler(page, moiAvec({ modules: ["COMPTE"], inactivite_session_min: 2 }), { "GET /taches": vide });
    await page.goto("/a-traiter");
    await expect(page.getByRole("heading", { name: /Bonjour Abdou/ })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Votre session va expirer" })).toHaveCount(0);

    await page.clock.fastForward(70_000);
    const alerte = page.getByRole("dialog", { name: "Votre session va expirer" });
    await expect(alerte).toBeVisible();
    await expect(alerte).toContainText(/Déconnexion dans \d+ s/);

    const avant = appels.filter((a) => a.chemin === "/auth/session").length;
    await alerte.getByRole("button", { name: "Rester connecté" }).click();
    await expect(alerte).toBeHidden();
    expect(appels.filter((a) => a.chemin === "/auth/session").length).toBeGreaterThan(avant);

    await page.clock.fastForward(130_000);
    await expect(page).toHaveURL(/\/connexion\?suivant=%2Fa-traiter&motif=expiree/);
  });

  test("tiroir sur mobile : ouverture, navigation et fermeture", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await ouvrirEtSimuler(page, MOI_COMPLET, { "GET /taches": vide });
    await page.goto("/a-traiter");
    await expect(menu(page)).toBeHidden();
    await page.getByRole("button", { name: "Menu" }).click();
    const tiroir = page.getByRole("dialog", { name: "Menu" });
    await expect(tiroir).toBeVisible();
    await expect(tiroir.getByRole("link", { name: "Journal d'audit" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tiroir).toBeHidden();

    await page.getByRole("button", { name: "Menu" }).click();
    await tiroir.getByRole("link", { name: "Mon compte" }).click();
    await expect(page).toHaveURL(/\/mon-compte$/);
    await expect(tiroir).toBeHidden();
    const debordement = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(debordement).toBeLessThanOrEqual(0);
  });
});
