import { expect, test, type Page } from "@playwright/test";
import { erreur, json, type Gestionnaire } from "./aide";
import { moiAvec, ouvrirEtSimuler, page as pageDe, paramsDe } from "./donnees";
import { gestionnairesAdmin, MOI_ADMIN } from "./donnees-f67";
import { absenceAdmin, AWA, CHEIKH, delegation, FATOU, ID_ABS, ID_DEL } from "./donnees-b13";

/** Écran F7 « Délégations » branché sur `/admin/absences` et `/admin/delegations` (B13). */

const ouvrir = (page: Page, extra: Record<string, Gestionnaire> = {}, moi: unknown = MOI_ADMIN) => ouvrirEtSimuler(page, moi, gestionnairesAdmin(extra));

test.describe("Administration · délégations et absences (F7, B13)", () => {
  test("listes filtrables : absences soumises et délégations actives par défaut", async ({ page }) => {
    const reqAbs: URLSearchParams[] = [];
    const reqDel: URLSearchParams[] = [];
    await ouvrir(page, {
      "GET /admin/absences": (_a, route) => {
        reqAbs.push(paramsDe(route));
        return json(route, pageDe([absenceAdmin("SOUMISE")]));
      },
      "GET /admin/delegations": (_a, route) => {
        reqDel.push(paramsDe(route));
        return json(route, pageDe([delegation("ACTIVE", { effective: true }), delegation("TERMINEE", { id: "d2", delegataire: { id: "x", nom: "Ousmane Fall" } })]));
      },
    });
    await page.goto("/administration/delegations");
    await expect(page.getByRole("navigation", { name: "Administration" }).getByRole("link", { name: "Délégations" })).toHaveAttribute("aria-current", "page");

    const absences = page.getByRole("region", { name: /Absences de l'établissement/ });
    const ligne = absences.getByRole("row").filter({ hasText: "Awa Diop" });
    await expect(ligne).toContainText("Congé");
    await expect(ligne).toContainText("Fatou Sarr");
    await expect(ligne).toContainText("Soumise");
    await expect(ligne).toContainText("Valideur : Mamadou Sow");
    expect(reqAbs[0]?.get("statut")).toBe("SOUMISE");

    const delegations = page.getByRole("region", { name: /Délégations de l'établissement/ });
    await expect(delegations.getByRole("row").filter({ hasText: "Cheikh Badiane" })).toContainText("En vigueur");
    await expect(delegations.getByRole("row").filter({ hasText: "Ousmane Fall" })).toContainText("Terminée");
    await expect(delegations.getByRole("row").filter({ hasText: "Ousmane Fall" }).getByRole("button", { name: /Révoquer/ })).toHaveCount(0);
    expect(reqDel[0]?.get("statut")).toBe("ACTIVE");

    await page.getByLabel("Statut de l'absence").selectOption("");
    await page.getByLabel("Du").first().fill("2026-11-01");
    await expect.poll(() => reqAbs.at(-1)?.get("du")).toBe("2026-11-01");
    expect(reqAbs.at(-1)?.get("statut")).toBeNull();
    await page.getByLabel("Statut de la délégation").selectOption("TERMINEE");
    await expect.poll(() => reqDel.at(-1)?.get("statut")).toBe("TERMINEE");
  });

  test("validation et refus motivé d'une absence soumise", async ({ page }) => {
    let etat = "SOUMISE";
    const appels = await ouvrir(page, {
      "GET /admin/absences": (_a, route) => json(route, pageDe([absenceAdmin(etat)])),
      "GET /admin/delegations": (_a, route) => json(route, pageDe([])),
      [`POST /absences/${ID_ABS}/valider`]: (_a, route) => erreur(route, 409, "POUVOIRS_INSUFFISANTS", "Pouvoirs insuffisants."),
      [`POST /absences/${ID_ABS}/refuser`]: (_a, route) => {
        etat = "REFUSEE";
        return json(route, absenceAdmin("REFUSEE"));
      },
    });
    await page.goto("/administration/delegations");
    await page.getByRole("button", { name: "Valider l'absence de Awa Diop" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "pouvoirs au moins égaux à ceux de l'absent" })).toBeVisible();

    await page.getByRole("button", { name: "Refuser l'absence de Awa Diop" }).click();
    const fenetre = page.getByRole("dialog", { name: "Refuser cette absence ?" });
    await fenetre.getByRole("button", { name: "Refuser l’absence" }).click();
    await expect(fenetre.getByText("Indiquez le motif du refus.")).toBeVisible();
    await fenetre.getByLabel("Motif du refus").fill("Clôture trimestrielle");
    await fenetre.getByRole("button", { name: "Refuser l’absence" }).click();
    await expect(page.getByText("Absence refusée")).toBeVisible();
    expect(appels.find((a) => a.chemin === `/absences/${ID_ABS}/refuser`)?.corps).toEqual({ motif: "Clôture trimestrielle" });
    await expect(page.getByRole("region", { name: /Absences de l'établissement/ })).toContainText("Refusée");
  });

  test("déclaration pour le compte d'un collaborateur : délégataire contrôlé (P5), validation immédiate", async ({ page }) => {
    const candidats: URLSearchParams[] = [];
    const appels = await ouvrir(page, {
      "GET /admin/absences": (_a, route) => json(route, pageDe([])),
      "GET /admin/delegations": (_a, route) => json(route, pageDe([])),
      "GET /admin/absences/candidats": (_a, route) => {
        const p = paramsDe(route);
        candidats.push(p);
        return json(route, p.get("pour") ? [CHEIKH, FATOU] : [AWA, CHEIKH, FATOU]);
      },
      "POST /admin/absences": (_a, route) => json(route, absenceAdmin("VALIDEE"), 201),
    });
    await page.goto("/administration/delegations");
    await expect(page.getByText("Aucune absence ne correspond à ces filtres.")).toBeVisible();
    await page.getByRole("button", { name: "+ Déclarer une absence" }).click();
    const fenetre = page.getByRole("dialog", { name: "Déclarer une absence" });

    await fenetre.getByRole("button", { name: "Déclarer l'absence" }).click();
    await expect(fenetre.getByText("Choisissez le collaborateur absent.")).toBeVisible();
    await expect(fenetre.getByText("Indiquez le premier jour d'absence.")).toBeVisible();

    await fenetre.getByRole("radiogroup", { name: "Collaborateur absent" }).getByLabel(/Awa Diop/).check();
    await expect.poll(() => candidats.at(-1)?.get("pour")).toBe(AWA.id);
    const delegataires = fenetre.getByRole("radiogroup", { name: "Délégataire" });
    await expect(delegataires.getByRole("radio", { name: /Fatou Ndiaye/ })).toBeDisabled();
    await expect(delegataires.getByText("Pouvoirs insuffisants")).toBeVisible();
    await delegataires.getByRole("radio", { name: /Cheikh Badiane/ }).check();
    await fenetre.getByLabel("Du").fill("2026-11-02");
    await fenetre.getByLabel("Au").fill("2026-11-06");
    await fenetre.getByLabel("Motif").selectOption("MISSION");
    await fenetre.getByRole("switch", { name: "Valider immédiatement" }).check();
    await fenetre.getByRole("button", { name: "Enregistrer et valider" }).click();

    await expect(page.getByText("Absence enregistrée et validée")).toBeVisible();
    expect(appels.find((a) => a.methode === "POST" && a.chemin === "/admin/absences")?.corps).toEqual({
      utilisateur_id: AWA.id,
      debut: "2026-11-02T00:00:00Z",
      fin: "2026-11-06T23:59:00Z",
      motif: "MISSION",
      commentaire: "",
      delegataire_id: CHEIKH.id,
      valider: true,
    });
  });

  test("déclaration refusée par l'API : sous-délégation interdite", async ({ page }) => {
    await ouvrir(page, {
      "GET /admin/absences": (_a, route) => json(route, pageDe([])),
      "GET /admin/delegations": (_a, route) => json(route, pageDe([])),
      "GET /admin/absences/candidats": (_a, route) => json(route, paramsDe(route).get("pour") ? [CHEIKH] : [AWA, CHEIKH]),
      "POST /admin/absences": (_a, route) => erreur(route, 409, "SOUS_DELEGATION_INTERDITE", "Sous-délégation interdite."),
    });
    await page.goto("/administration/delegations");
    await page.getByRole("button", { name: "+ Déclarer une absence" }).click();
    const fenetre = page.getByRole("dialog", { name: "Déclarer une absence" });
    await fenetre.getByRole("radiogroup", { name: "Collaborateur absent" }).getByLabel(/Awa Diop/).check();
    await fenetre.getByRole("radiogroup", { name: "Délégataire" }).getByLabel(/Cheikh Badiane/).check();
    await fenetre.getByLabel("Du").fill("2026-11-02");
    await fenetre.getByLabel("Au").fill("2026-11-06");
    await fenetre.getByRole("button", { name: "Déclarer l'absence" }).click();
    await expect(fenetre.getByRole("alert")).toContainText("la sous-délégation est interdite");
    await expect(fenetre).toBeVisible();
  });

  test("révocation motivée d'une délégation active", async ({ page }) => {
    let etat = "ACTIVE";
    const appels = await ouvrir(page, {
      "GET /admin/absences": (_a, route) => json(route, pageDe([])),
      "GET /admin/delegations": (_a, route) => json(route, pageDe([delegation(etat, { effective: etat === "ACTIVE" })])),
      [`POST /admin/delegations/${ID_DEL}/revoquer`]: (_a, route) => {
        etat = "TERMINEE";
        return json(route, delegation("TERMINEE"));
      },
    });
    await page.goto("/administration/delegations");
    await page.getByRole("button", { name: "Révoquer la délégation de Awa Diop à Cheikh Badiane" }).click();
    const fenetre = page.getByRole("dialog", { name: "Révoquer cette délégation ?" });
    await expect(fenetre).toContainText("L’absence reste enregistrée");
    await fenetre.getByRole("button", { name: "Révoquer", exact: true }).click();
    await expect(fenetre.getByText("Indiquez le motif de la révocation.")).toBeVisible();
    await fenetre.getByLabel("Motif de la révocation").fill("Délégataire muté");
    await fenetre.getByRole("button", { name: "Révoquer", exact: true }).click();
    await expect(page.getByText("Délégation révoquée")).toBeVisible();
    expect(appels.find((a) => a.chemin === `/admin/delegations/${ID_DEL}/revoquer`)?.corps).toEqual({ motif: "Délégataire muté" });
    // Le filtre par défaut (actives) n'affiche plus que des délégations terminées : aucune action.
    await expect(page.getByRole("button", { name: /Révoquer la délégation/ })).toHaveCount(0);
  });

  test("admin.utilisateurs seul : délégations en lecture, pas d'absences ; sans droit : accès refusé", async ({ page }) => {
    const appels = await ouvrir(
      page,
      { "GET /admin/delegations": (_a, route) => json(route, pageDe([delegation("ACTIVE")])) },
      moiAvec({ modules: ["COMPTE", "ADMINISTRATION"], permissions: ["admin.utilisateurs"] }),
    );
    await page.goto("/administration/delegations");
    await expect(page.getByRole("region", { name: /Délégations de l'établissement/ })).toContainText("Programmée");
    await expect(page.getByText("Consultation seule.", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: /Révoquer/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "+ Déclarer une absence" })).toHaveCount(0);
    expect(appels.some((a) => a.chemin === "/admin/absences")).toBe(false);
  });

  test("sans permission d'administration : accès refusé", async ({ page }) => {
    await ouvrir(page, {}, moiAvec({ modules: ["COMPTE", "ADMINISTRATION"], permissions: ["admin.roles"] }));
    await page.goto("/administration/delegations");
    await expect(page.getByText("Vous n'avez pas accès à cet écran.")).toBeVisible();
  });
});
