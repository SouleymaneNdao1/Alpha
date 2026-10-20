import { COMPTES, expect, seConnecter, test } from "./aide";

/**
 * Parcours 4 : le super-administrateur FYXOP se connecte à la console ; un utilisateur d'établissement
 * en est refusé (côté interface et côté API) ; réciproquement le super-administrateur n'entre pas dans
 * les routes d'un établissement (règle d'isolation n° 2).
 */
const menu = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "Navigation principale" });

test("le super-admin entre dans la console FYXOP, avec un menu réduit", async ({ page }) => {
  await seConnecter(page, COMPTES.superAdmin);
  await expect(page).toHaveURL(/\/console$/);
  await expect(page.getByRole("heading", { name: "Établissements", level: 1 })).toBeVisible();
  // Les deux établissements du jeu de démonstration sont listés par l'API de la plateforme.
  await expect(page.getByText("Établissement démo").first()).toBeVisible();
  await expect(page.getByText("Sahel Distribution").first()).toBeVisible();
  await expect(menu(page).getByRole("link")).toHaveText(["Établissements", "Journal de la plateforme"]);
  await expect(menu(page).getByRole("link", { name: "À traiter" })).toHaveCount(0);
  await expect(page.getByText("Aucun accès au contenu des dossiers.")).toBeVisible();

  // Le super-admin n'accède pas aux données d'un établissement : l'API répond 403.
  const taches = await page.request.get("/api/v1/taches");
  expect(taches.status()).toBe(403);
  expect((await taches.json()).code).toBeTruthy();
});

test("un utilisateur d'établissement n'accède pas à la console", async ({ page }) => {
  await seConnecter(page, COMPTES.admin);
  await expect(page).toHaveURL(/\/a-traiter$/);

  // Interface : /console et ses sous-pages ramènent à « À traiter ».
  await page.goto("/console");
  await expect(page).toHaveURL(/\/a-traiter$/);
  await page.goto("/console/journal");
  await expect(page).toHaveURL(/\/a-traiter$/);
  await expect(menu(page).getByRole("link", { name: "Établissements" })).toHaveCount(0);

  // API : refus côté serveur, au format {code, message, details}, sans fuite de la liste des établissements.
  for (const chemin of ["/api/v1/plateforme/etablissements", "/api/v1/plateforme/audit"]) {
    const reponse = await page.request.get(chemin);
    expect([401, 403, 404]).toContain(reponse.status());
    const corps = await reponse.json();
    expect(corps).toHaveProperty("code");
    expect(JSON.stringify(corps)).not.toContain("Sahel Distribution");
  }
});
