import { expect, test } from "@playwright/test";
import { erreur, json } from "./aide";
import { absence, ouvrirCompte } from "./donnees-f67";

const ID = "cccccccc-0000-4000-8000-000000000001";

test.describe("Validation d'une absence (F6)", () => {
  test("le responsable valide : la délégation devient active", async ({ page }) => {
    let etat = "SOUMISE";
    const appels = await ouvrirCompte(page, {
      [`GET /absences/${ID}`]: (_a, route) => json(route, { ...absence(etat), peut_decider: etat === "SOUMISE" }),
      [`POST /absences/${ID}/valider`]: (_a, route) => {
        etat = "VALIDEE";
        return json(route, { ...absence("VALIDEE"), peut_decider: false });
      },
    });
    await page.goto(`/absences/${ID}`);
    await expect(page.getByRole("heading", { name: "Demande d'absence · Abdou Kane" })).toBeVisible();
    await expect(page.getByText("Congés annuels")).toBeVisible();
    await expect(page.getByText("Fatou Sarr")).toBeVisible();
    await expect(page.getByText("Soumise")).toBeVisible();
    await page.getByRole("button", { name: "Valider" }).click();
    await expect(page.getByText("Absence validée")).toBeVisible();
    await expect(page.getByText("Validée", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Valider" })).toHaveCount(0);
    expect(appels.some((a) => a.methode === "POST" && a.chemin === `/absences/${ID}/valider`)).toBe(true);
  });

  test("refus : motif obligatoire, transmis au serveur", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      [`GET /absences/${ID}`]: (_a, route) => json(route, { ...absence("SOUMISE"), peut_decider: true }),
      [`POST /absences/${ID}/refuser`]: (_a, route) => json(route, { ...absence("REFUSEE", { motif_refus: "Clôture trimestrielle" }), peut_decider: false }),
    });
    await page.goto(`/absences/${ID}`);
    await page.getByRole("button", { name: "Refuser" }).click();
    const fenetre = page.getByRole("dialog", { name: "Refuser la demande d'absence" });
    const envoyer = fenetre.getByRole("button", { name: "Refuser la demande" });
    await expect(envoyer).toBeDisabled();
    await fenetre.getByLabel(/Motif du refus/).fill("Clôture trimestrielle");
    await envoyer.click();
    await expect(page.getByText("Absence refusée")).toBeVisible();
    await expect(page.getByText("Clôture trimestrielle")).toBeVisible();
    expect(appels.find((a) => a.chemin === `/absences/${ID}/refuser`)?.corps).toEqual({ motif: "Clôture trimestrielle" });
  });

  test("refus métier expliqué (pouvoirs insuffisants), lecture seule et introuvable", async ({ page }) => {
    await ouvrirCompte(page, {
      [`GET /absences/${ID}`]: (_a, route) => json(route, { ...absence("SOUMISE"), peut_decider: true }),
      [`POST /absences/${ID}/valider`]: (_a, route) => erreur(route, 409, "POUVOIRS_INSUFFISANTS", "Pouvoirs insuffisants."),
      "GET /absences/inconnue": (_a, route) => erreur(route, 404, "INTROUVABLE", "Introuvable."),
    });
    await page.goto(`/absences/${ID}`);
    await page.getByRole("button", { name: "Valider" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "pouvoirs au moins égaux" })).toBeVisible();
    await page.goto("/absences/inconnue");
    await expect(page.getByRole("heading", { name: "Demande introuvable" })).toBeVisible();
  });

  test("sans droit de décision : consultation seule", async ({ page }) => {
    await ouvrirCompte(page, { [`GET /absences/${ID}`]: (_a, route) => json(route, { ...absence("SOUMISE"), peut_decider: false }) });
    await page.goto(`/absences/${ID}`);
    await expect(page.getByText(/Vous ne pouvez pas décider de cette demande/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Valider" })).toHaveCount(0);
  });
});
