import { expect, test } from "@playwright/test";
import { erreur, json } from "./aide";
import { COMPTEURS, MOI_COMPLET, ouvrirEtSimuler, page as pageDe, paramsDe, TACHES } from "./donnees";

function filtrer(route: Parameters<typeof json>[0]) {
  const p = paramsDe(route);
  const mod = p.get("module");
  const groupe = p.get("groupe");
  return TACHES.filter((t) => (!mod || t.module === mod) && (!groupe || t.groupe === groupe));
}

test.describe("À traiter (F5)", () => {
  test("groupes par urgence, tuiles, puces et lignes conformes au prototype", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, { "GET /taches": (_a, route) => json(route, pageDe(filtrer(route))) });
    await page.goto("/a-traiter");
    await expect(page.getByRole("heading", { name: "Bonjour Abdou, voici ce qui vous attend" })).toBeVisible();
    await expect(page.getByText(/Établissement démo · tout ce qui attend votre décision/)).toBeVisible();

    for (const titre of ["En retard · 1", "Aujourd'hui · 2", "Cette semaine · 1", "Plus tard · 1"]) {
      await expect(page.getByRole("heading", { name: titre })).toBeVisible();
    }
    // Tuiles : valeurs des compteurs.
    await expect(page.getByRole("button", { name: /^En retard\s*1$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Aujourd'hui\s*3$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Cette semaine\s*3$/ })).toBeVisible();
    // Puces.
    await expect(page.getByRole("button", { name: `Tout ${COMPTEURS.total}` })).toBeVisible();
    await expect(page.getByRole("button", { name: "Crédit 4" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Décisions internes 3" })).toBeVisible();

    const ligne = page.getByRole("listitem").filter({ hasText: "REF-1" });
    await expect(ligne).toContainText("Demande de crédit Sow & Fils");
    await expect(ligne).toContainText("14 600 000 FCFA");
    await expect(ligne).toContainText("En retard d'1 jour");
    await expect(ligne.getByRole("link", { name: /Décider/ })).toHaveAttribute("href", "/dossiers/1");
    await expect(page.getByRole("listitem").filter({ hasText: "REF-2" })).toContainText("par délégation de Awa Diop");
    await expect(page.getByRole("listitem").filter({ hasText: "REF-3" }).getByRole("link", { name: /Valider/ })).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: "REF-5" })).toContainText("Sans échéance");
    await expect(page.getByText(/Vous serez absent \?/)).toBeVisible();
  });

  test("filtre par module : la requête porte le module et la liste se réduit", async ({ page }) => {
    const appels = await ouvrirEtSimuler(page, MOI_COMPLET, { "GET /taches": (_a, route) => json(route, pageDe(filtrer(route))) });
    await page.goto("/a-traiter");
    await expect(page.getByText("REF-5")).toBeVisible();
    await page.getByRole("button", { name: "Crédit 4" }).click();
    await expect(page.getByText("REF-5")).toHaveCount(0);
    await expect(page.getByText("REF-4")).toBeVisible();
    await expect(page.getByRole("button", { name: "Crédit 4" })).toHaveAttribute("aria-pressed", "true");
    expect(appels.some((a) => a.chemin === "/taches")).toBe(true);
    await page.getByRole("button", { name: `Tout ${COMPTEURS.total}` }).click();
    await expect(page.getByText("REF-5")).toBeVisible();
  });

  test("filtre par urgence depuis une tuile, et état vide filtré", async ({ page }) => {
    let derniere = "";
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => {
        derniere = paramsDe(route).get("groupe") ?? "";
        return json(route, pageDe(derniere === "CETTE_SEMAINE" ? [] : filtrer(route)));
      },
    });
    await page.goto("/a-traiter");
    await page.getByRole("button", { name: /^En retard\s*1$/ }).click();
    await expect(page.getByText("REF-3")).toHaveCount(0);
    await expect(page.getByText("REF-1")).toBeVisible();
    expect(derniere).toBe("EN_RETARD");
    await page.getByRole("button", { name: /^Cette semaine/ }).click();
    await expect(page.getByText("Rien à traiter pour ce filtre.")).toBeVisible();
    await page.getByRole("button", { name: "Afficher toutes les tâches" }).click();
    await expect(page.getByText("REF-1")).toBeVisible();
  });

  test("aucune tâche : message du prototype", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => json(route, pageDe([])),
      "GET /taches/compteurs": (_a, route) =>
        json(route, { total: 0, par_groupe: { EN_RETARD: 0, AUJOURDHUI: 0, CETTE_SEMAINE: 0, PLUS_TARD: 0 }, par_module: {} }),
    });
    await page.goto("/a-traiter");
    await expect(page.getByText("Rien à traiter pour le moment.")).toBeVisible();
  });

  test("permission refusée : écran « Accès refusé »", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => erreur(route, 403, "PERMISSION_REFUSEE", "Accès refusé."),
    });
    await page.goto("/a-traiter");
    await expect(page.getByRole("heading", { name: "Accès refusé" })).toBeVisible();
  });
});
