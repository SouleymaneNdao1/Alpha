import { test } from "@playwright/test";
import { saisirOtp } from "./aide";
import { ouvrirConsole } from "./donnees-f9";

/** Captures de revue : `CAPTURES_DIR=/chemin npm run test:e2e -- captures-f9`. */
const dossier = process.env.CAPTURES_DIR;
test.skip(!dossier, "CAPTURES_DIR non défini");

for (const [nom, viewport] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`captures F9 à ${nom}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await ouvrirConsole(page);
    await page.goto("/console");
    await page.getByText("Banque Atlantique Sénégal").waitFor();
    await page.screenshot({ path: `${dossier}/f9-liste-${nom}.png`, fullPage: true });
    await page.getByRole("button", { name: "+ Nouvel établissement" }).click();
    const d = page.getByRole("dialog", { name: "Nouvel établissement" });
    await d.getByLabel(/^Raison sociale/).fill("Banque du Sahel");
    await d.getByLabel(/^Code de l'établissement/).fill("banque-du-sahel");
    await d.getByLabel(/^Prénom/).fill("Awa");
    await d.getByLabel(/^Nom/).last().fill("Diop");
    await d.getByLabel(/^Adresse e-mail professionnelle/).fill("awa.diop@sahel.sn");
    await saisirOtp(page, "123456");
    await page.screenshot({ path: `${dossier}/f9-creation-${nom}.png` });
  });
}
