import { expect, test } from "@playwright/test";
import { erreur, json } from "./aide";
import { evenement, INDICATEURS, MOI_COMPLET, moiAvec, ouvrirEtSimuler, paramsDe } from "./donnees";

const ORIGINE = "http://localhost:3100";

test.describe("Journal d'audit (F8)", () => {
  test("liste, indicateurs et pagination par curseur (next absolu suivi)", async ({ page }) => {
    const urls: string[] = [];
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => {
        urls.push(route.request().url());
        const curseur = paramsDe(route).get("curseur");
        if (curseur === "page2") return json(route, { next: null, results: [evenement(2, { detail: "Seconde page" })] });
        return json(route, { next: `${ORIGINE}/api/v1/audit/evenements?curseur=page2&periode=7j&taille=50`, results: [evenement(1, { avant: { statut: "ACTIF" }, apres: { statut: "SUSPENDU" } })] });
      },
    });
    await page.goto("/journal");
    await expect(page.getByRole("heading", { name: "Journal d'audit" })).toBeVisible();
    await expect(page.getByText("128")).toBeVisible();
    await expect(page.getByText("Événements aujourd'hui")).toBeVisible();
    await expect(page.getByText("Connexions échouées (24 h)")).toBeVisible();
    await expect(page.getByText("Intégrité vérifiée")).toBeVisible();

    const table = page.getByRole("region", { name: "Événements du journal d'audit" });
    await expect(table).toContainText("Détail 1");
    await expect(table).toContainText("statut : ACTIF → SUSPENDU");
    await expect(table.getByRole("button", { name: /empreinte complète de l'événement 1/ })).toHaveText("a41f…9c2e");
    // La page suivante est chargée par la sentinelle (ou le bouton), avec le curseur de `next`.
    await expect(table).toContainText("Seconde page");
    expect(urls.some((u) => u.includes("curseur=page2"))).toBe(true);
    expect(urls[0]).toContain("periode=7j");
    await expect(page.getByText(/Fin du journal · 2 événements/)).toBeVisible();
  });

  test("filtres : recherche, catégorie et période sont envoyés à l'API", async ({ page }) => {
    const requetes: URLSearchParams[] = [];
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => {
        requetes.push(paramsDe(route));
        return json(route, { next: null, results: [evenement(1)] });
      },
    });
    await page.goto("/journal");
    await expect(page.getByText("Détail 1")).toBeVisible();
    await page.getByLabel("Rechercher dans le journal").fill("kane");
    await page.getByLabel("Catégorie").selectOption("CONNEXION");
    await page.getByLabel("Période").selectOption("30j");
    await expect.poll(() => requetes.at(-1)?.get("q")).toBe("kane");
    const derniere = requetes.at(-1)!;
    expect(derniere.get("categorie")).toBe("CONNEXION");
    expect(derniere.get("periode")).toBe("30j");
  });

  test("aucun résultat : message", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [] }),
    });
    await page.goto("/journal");
    await expect(page.getByText("Aucun événement ne correspond à ces filtres.")).toBeVisible();
  });

  test("export Excel avec les filtres courants", async ({ page }) => {
    let params: URLSearchParams | null = null;
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
      "GET /audit/export.xlsx": (_a, route) => {
        params = paramsDe(route);
        return route.fulfill({
          status: 200,
          contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          body: "PK-faux-classeur",
        });
      },
    });
    await page.goto("/journal");
    await page.getByLabel("Catégorie").selectOption("DECISION");
    const telechargement = page.waitForEvent("download");
    await page.getByRole("button", { name: "Exporter (Excel)" }).click();
    const fichier = await telechargement;
    expect(fichier.suggestedFilename()).toMatch(/^journal-audit-\d{4}-\d{2}-\d{2}\.xlsx$/);
    expect(params!.get("categorie")).toBe("DECISION");
    expect(params!.get("periode")).toBe("7j");
    await expect(page.getByText("Export du journal téléchargé")).toBeVisible();
  });

  test("export trop volumineux : message de l'API", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
      "GET /audit/export.xlsx": (_a, route) =>
        erreur(route, 400, "EXPORT_TROP_VOLUMINEUX", "L'export dépasse 50000 lignes : restreignez la période ou les filtres."),
    });
    await page.goto("/journal");
    await page.getByRole("button", { name: "Exporter (Excel)" }).click();
    await expect(page.getByText("Export trop volumineux")).toBeVisible();
    await expect(page.getByText(/restreignez la période/)).toBeVisible();
  });

  test("sans audit.export : pas de bouton d'export", async ({ page }) => {
    await ouvrirEtSimuler(page, moiAvec({ modules: ["COMPTE", "AUDIT"], permissions: ["audit.lecture"] }), {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
    });
    await page.goto("/journal");
    await expect(page.getByText("Détail 1")).toBeVisible();
    await expect(page.getByRole("button", { name: "Exporter (Excel)" })).toHaveCount(0);
  });

  test("accès refusé sans la permission de lecture", async ({ page }) => {
    await ouvrirEtSimuler(page, moiAvec({ modules: ["COMPTE"], permissions: [] }));
    await page.goto("/journal");
    await expect(page.getByRole("heading", { name: "Accès refusé" })).toBeVisible();
  });

  test("lancer un contrôle, le suivre jusqu'à son résultat", async ({ page }) => {
    let enCours = false;
    let interrogations = 0;
    const appels = await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => {
        if (enCours && ++interrogations >= 2) {
          enCours = false;
          return json(route, {
            ...INDICATEURS,
            controle_en_cours: false,
            dernier_controle: { ...INDICATEURS.dernier_controle, id: "c2", lance_le: "2026-10-19T09:00:00Z", termine_le: "2026-10-19T09:00:30Z" },
          });
        }
        return json(route, { ...INDICATEURS, controle_en_cours: enCours });
      },
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
      "GET /audit/controles": (_a, route) => json(route, { count: 0, next: null, previous: null, results: [] }),
      "POST /audit/controles": (_a, route) => {
        enCours = true;
        return json(route, { id: "c2", statut: "EN_COURS" }, 202);
      },
    });
    await page.goto("/journal");
    await expect(page.getByText("Intégrité vérifiée")).toBeVisible();
    await page.getByRole("button", { name: "Lancer un contrôle" }).click();
    await expect(page.getByText("Contrôle lancé")).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Contrôle en cours…" })).toBeVisible();
    expect(appels.filter((a) => a.methode === "POST" && a.chemin === "/audit/controles")).toHaveLength(1);
    await expect(page.getByText("Contrôle terminé : intégrité vérifiée")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Contrôle en cours…")).toHaveCount(0);
  });

  test("contrôle déjà en cours (409) : information, pas d'erreur", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) => json(route, INDICATEURS),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
      "POST /audit/controles": (_a, route) => erreur(route, 409, "CONTROLE_EN_COURS", "Un contrôle d'intégrité est déjà en cours."),
    });
    await page.goto("/journal");
    await page.getByRole("button", { name: "Lancer un contrôle" }).click();
    await expect(page.getByText("Un contrôle est déjà en cours")).toBeVisible();
  });

  test("chaîne rompue : carte rouge avec le numéro d'événement", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /audit/indicateurs": (_a, route) =>
        json(route, { ...INDICATEURS, dernier_controle: { ...INDICATEURS.dernier_controle, statut: "ROMPUE", premier_seq_invalide: 4242 } }),
      "GET /audit/evenements": (_a, route) => json(route, { next: null, results: [evenement(1)] }),
    });
    await page.goto("/journal");
    await expect(page.getByRole("alert").filter({ hasText: "Chaîne rompue à l'événement n° 4242" })).toBeVisible();
    await expect(page.getByText("Intégrité vérifiée")).toHaveCount(0);
  });
});
