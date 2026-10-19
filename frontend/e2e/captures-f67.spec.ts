import { test } from "@playwright/test";
import { json } from "./aide";
import { page as pageDe } from "./donnees";
import { fiche, evenementAdmin, MOI_ADMIN, ouvrirCompte, UTILISATEURS } from "./donnees-f67";

/** Captures de revue : `CAPTURES_DIR=/chemin npm run test:e2e -- captures-f67`. */
const dossier = process.env.CAPTURES_DIR;
test.skip(!dossier, "CAPTURES_DIR non défini");

for (const [nom, viewport] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`captures F6 et F7 à ${nom}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await ouvrirCompte(page, {
      "GET /admin/utilisateurs": (_a, route) => json(route, pageDe(UTILISATEURS)),
      "GET /admin/utilisateurs/historique": (_a, route) => json(route, [evenementAdmin(31), evenementAdmin(30, { objet_libelle: "Compte fournisseur · Emballages du Sahel", action_libelle: "Invitation" })]),
      "GET /admin/roles": (_a, route) =>
        json(route, [{ id: "r2", code: "daf", libelle: "DAF", description: "", permissions: [], est_systeme: false, actif: true, ordre: 1, nb_titulaires: 2, vacant: false }]),
      "GET /admin/utilisateurs/u1": (_a, route) => json(route, fiche(UTILISATEURS[0]!)),
    }, MOI_ADMIN);
    await page.goto("/mon-compte?onglet=securite");
    await page.getByText("Safari sur iPhone").waitFor();
    await page.screenshot({ path: `${dossier}/f67-mon-compte-securite-${nom}.png`, fullPage: true });
    await page.goto("/administration/utilisateurs");
    await page.getByText("Khady").waitFor();
    await page.screenshot({ path: `${dossier}/f67-utilisateurs-${nom}.png`, fullPage: true });
  });
}
