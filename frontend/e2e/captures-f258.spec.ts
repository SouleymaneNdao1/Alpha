import { test } from "@playwright/test";
import { json } from "./aide";
import { evenement, INDICATEURS, MOI_COMPLET, ouvrirEtSimuler, page as pageDe, TACHES } from "./donnees";

/** Captures de revue : `CAPTURES_DIR=/chemin npm run test:e2e -- captures-f258`. */
const dossier = process.env.CAPTURES_DIR;
test.skip(!dossier, "CAPTURES_DIR non défini");

for (const [nom, viewport] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`captures F2, F5, F8 à ${nom}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => json(route, pageDe(TACHES)),
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) =>
        json(route, {
          next: null,
          results: Array.from({ length: 8 }, (_, i) =>
            evenement(8 - i, i === 1 ? { action_libelle: "Modification du compte", avant: { statut: "ACTIF" }, apres: { statut: "SUSPENDU" } } : {}),
          ),
        }),
    });
    await page.goto("/a-traiter");
    await page.getByText("REF-5").waitFor();
    await page.screenshot({ path: `${dossier}/f258-a-traiter-${nom}.png`, fullPage: true });
    await page.goto("/journal");
    await page.getByText("Détail 8").waitFor();
    await page.screenshot({ path: `${dossier}/f258-journal-${nom}.png`, fullPage: true });
  });
}
