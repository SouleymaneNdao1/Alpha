import { test } from "@playwright/test";
import { CODES_SECOURS, json, QR_SVG, saisirOtp, simulerApi } from "./aide";

/** Captures d'écran pour la revue visuelle : `CAPTURES_DIR=/chemin npm run test:e2e -- captures`. */
const dossier = process.env.CAPTURES_DIR;
test.skip(!dossier, "CAPTURES_DIR non défini");

for (const [nom, viewport] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`captures ${nom}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await simulerApi(page, {
      "POST /auth/connexion": (_a, route) => json(route, { etape: "MFA_REQUIS", methodes: ["TOTP", "CODE_SECOURS"] }),
      "GET /auth/activation/j": (_a, route) =>
        json(route, { prenom: "Abdou", etablissement: "Établissement démo", role: "DAF", etape: "INVITE" }),
      "POST /auth/activation/j/mot-de-passe": (_a, route) => route.fulfill({ status: 204 }),
      "POST /auth/activation/j/authenticator": (_a, route) =>
        json(route, { qr_svg: QR_SVG, secret_affichable: "JBSW Y3DP EHPK 3PXP", emetteur: "ALPHA", compte: "a.kane@etablissement-demo.sn" }),
      "POST /auth/activation/j/authenticator/confirmer": (_a, route) => json(route, { codes_secours: CODES_SECOURS }),
    });
    const cap = (n: string) => page.screenshot({ path: `${dossier}/f34-${n}-${nom}.png`, fullPage: true });

    await page.goto("/connexion");
    await cap("connexion");
    await page.getByLabel("Adresse e-mail professionnelle").fill("a.kane@etablissement-demo.sn");
    await page.getByLabel("Mot de passe", { exact: true }).fill("Mot-de-passe-12!");
    await page.getByRole("button", { name: "Continuer" }).click();
    await page.getByRole("heading", { name: "Double authentification" }).waitFor();
    await cap("mfa");

    await page.goto("/activation?jeton=j");
    await page.getByLabel("Nouveau mot de passe").fill("Mot-de-passe-12!");
    await cap("activation-1");
    await page.getByLabel("Confirmer le mot de passe").fill("Mot-de-passe-12!");
    await page.getByRole("button", { name: "Continuer" }).click();
    await page.getByRole("heading", { name: "Associez votre téléphone" }).waitFor();
    await cap("activation-2");
    await page.getByRole("button", { name: /Suivant|Continuer/ }).click();
    await page.getByRole("heading", { name: "Vérifiez votre téléphone" }).waitFor();
    await saisirOtp(page, "12345");
    await cap("activation-3-verification");
    await page.keyboard.type("6");
    await page.getByRole("heading", { name: "Vos codes de secours" }).waitFor();
    await cap("activation-3-codes");
  });
}
