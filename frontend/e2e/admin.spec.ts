import { expect, test } from "@playwright/test";
import { erreur, json, saisirOtp } from "./aide";
import { moiAvec, ouvrirEtSimuler, page as pageDe, paramsDe } from "./donnees";
import { evenementAdmin, fiche, gestionnairesAdmin, MOI_ADMIN, PARAMETRES, ROLES, signalement, UTILISATEURS, utilisateur } from "./donnees-f67";
import type { Gestionnaire } from "./aide";

const ouvrir = (page: import("@playwright/test").Page, extra: Record<string, Gestionnaire> = {}, moi: unknown = MOI_ADMIN) =>
  ouvrirEtSimuler(page, moi, gestionnairesAdmin(extra));

test.describe("Administration · utilisateurs (F7)", () => {
  test("liste conforme au prototype, filtres envoyés à l'API et historique", async ({ page }) => {
    const requetes: URLSearchParams[] = [];
    await ouvrir(page, {
      "GET /admin/utilisateurs": (_a, route) => {
        requetes.push(paramsDe(route));
        return json(route, pageDe(UTILISATEURS));
      },
      "GET /admin/utilisateurs/historique": (_a, route) => json(route, [evenementAdmin(31)]),
    });
    await page.goto("/administration/utilisateurs");
    await expect(page.getByRole("heading", { name: "Utilisateurs et rôles", level: 1 })).toBeVisible();
    await expect(page.getByText("Établissement démo · comptes, catalogue des rôles")).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Administration" });
    for (const nom of ["Utilisateurs", "Catalogue des rôles", "Rôles et habilitations", "Délégations", "Unités et périmètres", "Sécurité"]) {
      await expect(nav.getByRole("link", { name: nom })).toBeVisible();
    }
    await expect(nav.getByRole("link", { name: "Utilisateurs" })).toHaveAttribute("aria-current", "page");

    const table = page.getByRole("region", { name: /Utilisateurs de l'établissement/ });
    for (const col of ["Utilisateur", "Rôle", "Périmètre", "Authenticator", "Dernière connexion", "Statut"]) {
      await expect(table.getByRole("columnheader", { name: col })).toBeVisible();
    }
    const ligne = table.getByRole("row").filter({ hasText: "Ibrahima" });
    await expect(ligne).toContainText("Administrateur ALPHA");
    await expect(ligne).toContainText("Activée");
    await expect(ligne).toContainText("12/10 08:05");
    await expect(ligne.getByText("Actif")).toBeVisible();
    await expect(table.getByRole("row").filter({ hasText: "Moussa" })).toContainText("Invité");
    await expect(table.getByRole("row").filter({ hasText: "Moussa" })).toContainText("Non configurée");
    await expect(table.getByRole("row").filter({ hasText: "Moussa" })).toContainText("—");
    await expect(table.getByRole("row").filter({ hasText: "Khady" })).toContainText("Verrouillé");
    await expect(ligne.getByRole("link", { name: "Modifier Ibrahima Ndiaye" })).toHaveAttribute("href", "/administration/utilisateurs/u1");

    await page.getByPlaceholder("Nom, e-mail…").fill("sarr");
    await page.getByLabel("Rôle", { exact: true }).selectOption("r2");
    await expect.poll(() => requetes.at(-1)?.get("q")).toBe("sarr");
    expect(requetes.at(-1)?.get("role_id")).toBe("r2");

    const histo = page.getByRole("region", { name: /Dernières décisions/ });
    await expect(page.getByText("Les 3 dernières décisions. Rien n'est supprimé ni modifiable.")).toBeVisible();
    await expect(histo).toContainText("Rôle « Responsable RH » attribué à Aminata Diallo");
    await expect(histo).toContainText("Ibrahima Ndiaye");
  });

  test("invitation : e-mail déjà utilisé puis succès", async ({ page }) => {
    let essais = 0;
    const appels = await ouvrir(page, {
      "GET /admin/utilisateurs": (_a, route) => json(route, pageDe(UTILISATEURS)),
      "GET /admin/utilisateurs/historique": (_a, route) => json(route, []),
      "POST /admin/utilisateurs": (a, route) => {
        essais += 1;
        if (essais === 1) return erreur(route, 409, "EMAIL_EXISTE", "E-mail existant.");
        return json(route, fiche(utilisateur("u9", "Awa", "Diop", { statut: "INVITE" })), 201);
      },
    });
    await page.goto("/administration/utilisateurs");
    await page.getByRole("button", { name: "+ Inviter un utilisateur" }).click();
    const fenetre = page.getByRole("dialog", { name: "Inviter un utilisateur" });
    await fenetre.getByRole("button", { name: "Envoyer l’invitation" }).click();
    await expect(fenetre.getByText("Saisissez le prénom.")).toBeVisible();
    await expect(fenetre.getByText("Choisissez un rôle.")).toBeVisible();

    await fenetre.getByLabel(/^Prénom\b/).fill("Awa");
    await fenetre.getByLabel(/^Nom\b/).fill("Diop");
    await fenetre.getByLabel("Adresse e-mail professionnelle").fill("a.diop@etablissement-demo.sn");
    await fenetre.getByLabel(/^Rôle\b/).selectOption({ label: "DAF" });
    await fenetre.getByRole("button", { name: "Envoyer l’invitation" }).click();
    await expect(fenetre.getByText("Cette adresse e-mail est déjà utilisée.")).toBeVisible();

    await fenetre.getByLabel("Adresse e-mail professionnelle").fill("awa.diop@etablissement-demo.sn");
    await fenetre.getByRole("button", { name: "Envoyer l’invitation" }).click();
    await expect(page.getByText("Invitation envoyée")).toBeVisible();
    await expect(fenetre).toBeHidden();
    const envoi = appels.filter((a) => a.methode === "POST" && a.chemin === "/admin/utilisateurs").at(-1)!;
    expect(envoi.corps).toEqual({ email: "awa.diop@etablissement-demo.sn", prenom: "Awa", nom: "Diop", role_id: "r2", unite_id: null, telephone_mobile: null });
  });

  test("fiche : suspension refusée pour le dernier administrateur (409 expliqué)", async ({ page }) => {
    const u1 = fiche(UTILISATEURS[0]!, { sessions_actives: [{ id: "s1", appareil: "Chrome", ip: "10.0.0.1", methode_mfa: "TOTP", cree_le: "2026-10-19T08:00:00Z", derniere_activite: "2026-10-19T08:30:00Z" }] });
    const appels = await ouvrir(page, {
      "GET /admin/utilisateurs/u1": (_a, route) => json(route, u1),
      "GET /admin/utilisateurs": (_a, route) => json(route, pageDe(UTILISATEURS)),
      "POST /admin/utilisateurs/u1/suspendre": (_a, route) => erreur(route, 409, "DERNIER_ADMINISTRATEUR", "Dernier administrateur."),
    });
    await page.goto("/administration/utilisateurs/u1");
    await expect(page.getByRole("heading", { name: "Ibrahima Ndiaye", level: 1 })).toBeVisible();
    await expect(page.getByRole("region", { name: "Affectations en cours" })).toContainText("Administrateur ALPHA");
    await expect(page.getByRole("region", { name: "Sessions actives de l'utilisateur" })).toContainText("Chrome");

    await page.getByRole("button", { name: "Suspendre", exact: true }).click();
    const fenetre = page.getByRole("dialog", { name: "Suspendre Ibrahima Ndiaye ?" });
    const confirmer = fenetre.getByRole("button", { name: "Suspendre le compte" });
    await expect(confirmer).toBeDisabled();
    await fenetre.getByLabel(/Motif de la suspension/).fill("Départ de l'établissement");
    await confirmer.click();
    await expect(fenetre.getByRole("alert")).toContainText("il doit rester au moins un administrateur actif");
    await expect(fenetre.getByRole("alert")).toContainText("Attribuez d'abord");
    expect(appels.find((a) => a.chemin === "/admin/utilisateurs/u1/suspendre")?.corps).toEqual({ motif: "Départ de l'établissement" });
    await expect(fenetre).toBeVisible();
  });

  test("fiche : retrait du dernier rôle administrateur refusé, modification et réactivation", async ({ page }) => {
    let u2 = fiche(UTILISATEURS[1]!, { statut: "SUSPENDU" });
    const appels = await ouvrir(page, {
      "GET /admin/utilisateurs/u2": (_a, route) => json(route, u2),
      "GET /admin/utilisateurs": (_a, route) => json(route, pageDe(UTILISATEURS)),
      "POST /admin/affectations/af1/terminer": (_a, route) => erreur(route, 409, "DERNIER_ADMINISTRATEUR", "Dernier administrateur."),
      "POST /admin/utilisateurs/u2/reactiver": (_a, route) => {
        u2 = { ...u2, statut: "ACTIF" };
        return json(route, u2);
      },
      "PATCH /admin/utilisateurs/u2": (a, route) => json(route, { ...u2, ...a.corps }),
    });
    await page.goto("/administration/utilisateurs/u2");
    await page.getByRole("button", { name: /Retirer le rôle/ }).click();
    const fenetre = page.getByRole("dialog", { name: /Retirer le rôle/ });
    await fenetre.getByRole("button", { name: "Retirer le rôle" }).click();
    await expect(fenetre.getByRole("alert")).toContainText("au moins un administrateur actif");
    await fenetre.getByRole("button", { name: "Annuler" }).click();

    await page.getByLabel("Téléphone mobile").fill("+221771112233");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Fiche enregistrée")).toBeVisible();
    expect(appels.find((a) => a.methode === "PATCH")?.corps).toMatchObject({ telephone_mobile: "+221771112233" });

    await page.getByRole("button", { name: "Réactiver" }).click();
    await expect(page.getByText("Compte réactivé")).toBeVisible();
  });

  test("sans permission admin.utilisateurs : pas de liste, accès refusé", async ({ page }) => {
    await ouvrir(page, {}, moiAvec({ modules: ["COMPTE", "ADMINISTRATION"], permissions: ["admin.securite"] }));
    await page.goto("/administration/utilisateurs");
    await expect(page.getByRole("heading", { name: "Accès refusé" })).toBeVisible();
    // Le menu pointe vers la première page accessible et l'onglet Utilisateurs est masqué.
    await expect(page.getByRole("link", { name: "Administration" })).toHaveAttribute("href", "/administration/securite");
    await expect(page.getByRole("navigation", { name: "Administration" }).getByRole("link")).toHaveCount(1);
  });
});

test.describe("Administration · rôles, unités, sécurité (F7)", () => {
  test("catalogue des rôles : titulaires, vacant, système, modification dans un panneau", async ({ page }) => {
    let roles = ROLES;
    const appels = await ouvrir(page, {
      "GET /admin/roles": (_a, route) => json(route, roles),
      "PATCH /admin/roles/r2": (a, route) => {
        roles = roles.map((r) => (r.id === "r2" ? { ...r, ...a.corps } : r));
        return json(route, roles[1]);
      },
    });
    await page.goto("/administration/roles");
    const table = page.getByRole("region", { name: "Catalogue des rôles" });
    await expect(table.getByRole("row").filter({ hasText: "Chef de service" })).toContainText("Vacant");
    await expect(table.getByRole("row").filter({ hasText: "Administrateur ALPHA" })).toContainText("Système");
    await expect(table.getByRole("row").filter({ hasText: "Administrateur ALPHA" }).getByRole("button", { name: /Désactiver/ })).toHaveCount(0);

    await table.getByRole("button", { name: "Modifier le rôle DAF" }).click();
    const panneau = page.getByRole("dialog", { name: /Modifier le rôle « DAF »/ });
    await panneau.getByLabel("Libellé").fill("Directeur financier");
    await expect(panneau.getByLabel(/Journal d'audit \(lecture\)/)).toBeChecked();
    await panneau.getByLabel(/Rôles et habilitations/).check();
    await panneau.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Rôle enregistré")).toBeVisible();
    await expect(panneau).toBeHidden();
    expect(appels.find((a) => a.methode === "PATCH" && a.chemin === "/admin/roles/r2")?.corps).toEqual({
      libelle: "Directeur financier",
      description: "Directeur administratif et financier",
      permissions: ["audit.lecture", "admin.roles"],
    });
    await expect(table).toContainText("Directeur financier");
  });

  test("catalogue : désactivation du rôle du dernier administrateur refusée", async ({ page }) => {
    await ouvrir(page, {
      "POST /admin/roles/r2/desactiver": (_a, route) => erreur(route, 409, "DERNIER_ADMINISTRATEUR", "Dernier administrateur."),
    });
    await page.goto("/administration/roles");
    await page.getByRole("button", { name: "Désactiver le rôle DAF" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "au moins un administrateur actif" })).toBeVisible();
  });

  test("habilitations : matrice rôle × permission, rôles système verrouillés, enregistrement", async ({ page }) => {
    const appels = await ouvrir(page, { "PATCH /admin/roles/r3": (_a, route) => json(route, ROLES[2]) });
    await page.goto("/administration/habilitations");
    await expect(page.getByRole("checkbox", { name: "Administrateur ALPHA : Utilisateurs" })).toBeDisabled();
    await expect(page.getByRole("checkbox", { name: "Administrateur ALPHA : Utilisateurs" })).toBeChecked();
    const enregistrer = page.getByRole("button", { name: /^Enregistrer/ });
    await expect(enregistrer).toBeDisabled();
    await page.getByRole("checkbox", { name: "Chef de service : Journal d'audit (lecture)" }).check();
    await expect(page.getByRole("button", { name: "Enregistrer (1)" })).toBeEnabled();
    await page.getByRole("button", { name: "Enregistrer (1)" }).click();
    await expect(page.getByText("Habilitations enregistrées")).toBeVisible();
    expect(appels.find((a) => a.methode === "PATCH")?.corps).toEqual({ libelle: "Chef de service", permissions: ["audit.lecture"] });
  });

  test("unités : arbre et création", async ({ page }) => {
    const appels = await ouvrir(page, {
      "GET /admin/unites": (_a, route) =>
        json(route, [{ id: "un1", parent_id: null, type: "DIRECTION", code: "DAF", libelle: "Direction administrative et financière", actif: true, enfants: [{ id: "un2", parent_id: "un1", type: "SERVICE", code: "BUD", libelle: "Budget", actif: true, enfants: [] }] }]),
      "POST /admin/unites": (a, route) => json(route, { id: "un3", enfants: [], actif: true, ...a.corps }, 201),
    });
    await page.goto("/administration/organisation");
    const table = page.getByRole("region", { name: "Unités organisationnelles" });
    await expect(table).toContainText("Direction administrative et financière");
    await expect(table.getByRole("row").filter({ hasText: "Budget" })).toContainText("Service");
    await page.getByRole("button", { name: "+ Nouvelle unité" }).click();
    const fenetre = page.getByRole("dialog", { name: "Nouvelle unité" });
    await fenetre.getByLabel("Libellé").fill("Agence de Thiès");
    await fenetre.getByLabel("Code").fill("THI");
    await fenetre.getByLabel("Type").selectOption("AGENCE");
    await fenetre.getByLabel("Unité parente").selectOption("un1");
    await fenetre.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Unité créée")).toBeVisible();
    expect(appels.find((a) => a.methode === "POST" && a.chemin === "/admin/unites")?.corps).toEqual({ type: "AGENCE", code: "THI", libelle: "Agence de Thiès", parent_id: "un1", actif: true });
  });

  test("délégations : message clair tant que l'API d'administration n'existe pas", async ({ page }) => {
    await ouvrir(page);
    await page.goto("/administration/delegations");
    await expect(page.getByRole("status")).toContainText("n’est pas encore disponible");
  });

  test("paramètres de sécurité : seuls les réglages modifiés partent avec le code TOTP", async ({ page }) => {
    let essais = 0;
    const appels = await ouvrir(page, {
      "GET /admin/parametres-securite": (_a, route) => json(route, PARAMETRES),
      "GET /admin/signalements-telephone": (_a, route) => json(route, pageDe([])),
      "PATCH /admin/parametres-securite": (a, route) => {
        essais += 1;
        if (essais === 1) return erreur(route, 401, "CODE_INVALIDE", "Code de confirmation invalide.");
        return json(route, { ...PARAMETRES, inactivite_session_min: 20 });
      },
    });
    await page.goto("/administration/securite");
    await expect(page.getByLabel(/Inactivité avant déconnexion/)).toHaveValue("15");
    await expect(page.getByRole("button", { name: "Enregistrer les paramètres" })).toBeDisabled();

    await page.getByLabel(/Inactivité avant déconnexion/).fill("90");
    await page.getByRole("button", { name: "Enregistrer les paramètres" }).click();
    await expect(page.getByText("Valeur attendue : 5 à 60.")).toBeVisible();
    await page.getByLabel(/Inactivité avant déconnexion/).fill("20");
    await page.getByRole("button", { name: "Enregistrer les paramètres" }).click();

    const fenetre = page.getByRole("dialog", { name: "Confirmer la modification" });
    await expect(fenetre).toContainText("1 réglage de sécurité");
    await saisirOtp(page, "111111");
    await fenetre.getByRole("button", { name: "Confirmer et enregistrer" }).click();
    await expect(fenetre.getByText(/Code invalide ou expiré/)).toBeVisible();
    await saisirOtp(page, "222222");
    await fenetre.getByRole("button", { name: "Confirmer et enregistrer" }).click();
    await expect(page.getByText("Paramètres de sécurité enregistrés")).toBeVisible();
    await expect(fenetre).toBeHidden();
    const envois = appels.filter((a) => a.methode === "PATCH" && a.chemin === "/admin/parametres-securite");
    expect(envois).toHaveLength(2);
    expect(envois[1]!.corps).toEqual({ inactivite_session_min: 20, code: "222222" });
  });

  test("signalement « téléphone perdu » traité : vérification d'identité + code", async ({ page }) => {
    let etat = "OUVERT";
    const appels = await ouvrir(page, {
      "GET /admin/parametres-securite": (_a, route) => json(route, PARAMETRES),
      "GET /admin/signalements-telephone": (_a, route) => json(route, pageDe([signalement("sg1", etat, etat === "OUVERT" ? {} : { traite_par: { id: "u1", nom: "Ibrahima Ndiaye" } })])),
      "POST /admin/signalements-telephone/sg1/reinitialiser": (_a, route) => {
        etat = "REINITIALISE";
        return json(route, signalement("sg1", etat));
      },
    });
    await page.goto("/administration/securite");
    const table = page.getByRole("region", { name: "Signalements téléphone perdu" });
    await expect(table).toContainText("Fatou Sarr");
    await expect(table).toContainText("Ouvert");
    await expect(page.getByRole("heading", { name: /1 ouvert/ })).toBeVisible();

    await table.getByRole("button", { name: "Réinitialiser l'accès de Fatou Sarr" }).click();
    const fenetre = page.getByRole("dialog", { name: "Réinitialiser l'accès de Fatou Sarr" });
    const valider = fenetre.getByRole("button", { name: "Réinitialiser l'accès" });
    await saisirOtp(page, "123456");
    await expect(valider).toBeDisabled();
    await fenetre.getByLabel(/Vérification d'identité effectuée/).selectOption("VISIO");
    await fenetre.getByLabel("Commentaire").fill("Appel vidéo avec pièce d'identité");
    await valider.click();
    await expect(page.getByText("Accès réinitialisé")).toBeVisible();
    expect(appels.find((a) => a.chemin === "/admin/signalements-telephone/sg1/reinitialiser")?.corps).toEqual({
      code: "123456",
      commentaire: "Appel vidéo avec pièce d'identité",
      mode_verification: "VISIO",
    });
    await expect(table).toContainText("Réinitialisé");
    await expect(table).toContainText("Ibrahima Ndiaye");
  });

  test("signalement : auto-traitement interdit expliqué", async ({ page }) => {
    await ouvrir(page, {
      "GET /admin/parametres-securite": (_a, route) => json(route, PARAMETRES),
      "GET /admin/signalements-telephone": (_a, route) => json(route, pageDe([signalement("sg1", "OUVERT")])),
      "POST /admin/signalements-telephone/sg1/annuler": (_a, route) => erreur(route, 403, "AUTO_TRAITEMENT_INTERDIT", "Interdit.", { recours_fyxop: true }),
    });
    await page.goto("/administration/securite");
    await page.getByRole("button", { name: "Annuler le signalement de Fatou Sarr" }).click();
    const fenetre = page.getByRole("dialog", { name: "Annuler le signalement de Fatou Sarr" });
    await saisirOtp(page, "123456");
    await fenetre.getByRole("button", { name: "Annuler le signalement" }).click();
    await expect(fenetre.getByRole("alert")).toContainText("Vous ne pouvez pas traiter votre propre signalement");
    await expect(fenetre.getByRole("alert")).toContainText("demande écrite signée à FYXOP");
  });
});
