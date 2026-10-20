import { test } from "@playwright/test";
import { json } from "./aide";
import { ouvrirEtSimuler, page as pageDe, paramsDe } from "./donnees";
import { gestionnairesAdmin, MOI_ADMIN } from "./donnees-f67";
import { absenceAdmin, AWA, CHEIKH, delegation, FATOU } from "./donnees-b13";

/** Captures de revue de l'écran « Délégations » : `CAPTURES_DIR=/chemin npm run test:e2e -- captures-b13`. */
const dossier = process.env.CAPTURES_DIR;
test.skip(!dossier, "CAPTURES_DIR non défini");

for (const [nom, viewport] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`captures B13 à ${nom}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await ouvrirEtSimuler(
      page,
      MOI_ADMIN,
      gestionnairesAdmin({
        "GET /admin/absences": (_a, route) =>
          json(route, pageDe([absenceAdmin("SOUMISE"), absenceAdmin("REFUSEE", { id: "a2", demandeur: { id: "x", nom: "Moussa Sarr" }, motif_refus: "Clôture trimestrielle", peut_decider: false })])),
        "GET /admin/delegations": (_a, route) =>
          json(route, pageDe([delegation("ACTIVE", { effective: true }), delegation("ACTIVE", { id: "d2", delegant: { id: "y", nom: "Khady Fall" }, role: { id: "r", libelle: "DAF" } }), delegation("TERMINEE", { id: "d3" })])),
        "GET /admin/absences/candidats": (_a, route) => json(route, paramsDe(route).get("pour") ? [CHEIKH, FATOU] : [AWA, CHEIKH, FATOU]),
      }),
    );
    await page.goto("/administration/delegations");
    await page.getByText("Khady Fall").waitFor();
    await page.screenshot({ path: `${dossier}/b13-delegations-${nom}.png`, fullPage: true });
    await page.getByRole("button", { name: "+ Déclarer une absence" }).click();
    await page.getByRole("radiogroup", { name: "Collaborateur absent" }).getByLabel(/Awa Diop/).check();
    await page.getByText("Pouvoirs insuffisants").waitFor();
    await page.screenshot({ path: `${dossier}/b13-declaration-${nom}.png`, fullPage: true });
  });
}
