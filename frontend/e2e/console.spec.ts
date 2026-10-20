import { expect, test, type Page } from "@playwright/test";
import { erreur, json, MOI, ouvrirSession, saisirOtp, simulerApi } from "./aide";
import { evenement, MOI_COMPLET, moiAvec, paramsDe } from "./donnees";
import { detail, ETABLISSEMENTS, etablissement, MOI_SUPER_ADMIN, ouvrirConsole } from "./donnees-f9";

const ORIGINE = "http://localhost:3100";
const menu = (page: Page) => page.getByRole("navigation", { name: "Navigation principale" });

async function remplirCreation(page: Page, extra: { code?: string; email?: string } = {}) {
  await page.getByRole("button", { name: "+ Nouvel établissement" }).click();
  const d = page.getByRole("dialog", { name: "Nouvel établissement" });
  await d.getByLabel(/^Raison sociale/).fill("Banque du Sahel");
  await d.getByLabel(/^Code de l'établissement/).fill(extra.code ?? "banque-du-sahel");
  await d.getByLabel(/^Prénom/).fill("Awa");
  await d.getByLabel(/^Nom/, { exact: false }).last().fill("Diop");
  await d.getByLabel(/^Adresse e-mail professionnelle/).fill(extra.email ?? "awa.diop@sahel.sn");
  return d;
}

test.describe("Console FYXOP (F9)", () => {
  test("le super-admin est dirigé vers /console après la connexion, avec un menu réduit", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": (_a, route) => json(route, { etape: "MFA_REQUIS", methodes: ["TOTP"] }),
      "POST /auth/mfa": async (_a, route, p) => {
        await ouvrirSession(p);
        return json(route, { utilisateur: MOI_SUPER_ADMIN, codes_secours_restants: 8 });
      },
      "GET /auth/session": (_a, route) => json(route, MOI_SUPER_ADMIN),
      "GET /plateforme/etablissements": (_a, route) => json(route, ETABLISSEMENTS),
    });
    await page.goto("/connexion");
    await page.getByLabel("Adresse e-mail professionnelle").fill("root@fyxop.com");
    await page.getByLabel("Mot de passe", { exact: true }).fill("Mot-de-passe-12!");
    await page.getByRole("button", { name: "Continuer" }).click();
    await saisirOtp(page, "123456");
    await expect(page).toHaveURL(/\/console$/);
    await expect(page.getByRole("heading", { name: "Établissements", level: 1 })).toBeVisible();

    // Menu : la console et la déconnexion seulement.
    await expect(menu(page).getByRole("link")).toHaveText(["Établissements", "Journal de la plateforme"]);
    await expect(menu(page).getByRole("link", { name: "À traiter" })).toHaveCount(0);
    await expect(menu(page).getByRole("link", { name: "Administration" })).toHaveCount(0);
    await expect(menu(page).getByRole("link", { name: "Mon compte" })).toHaveCount(0);
    await page.locator("aside").getByRole("button", { name: /Abdou Kane/ }).click();
    await expect(page.getByRole("menuitem")).toHaveText(["Se déconnecter"]);
    // Rappel permanent : aucun contenu de dossier.
    await expect(page.getByText("Aucun accès au contenu des dossiers.")).toBeVisible();
  });

  test("/console est interdite à un utilisateur d'établissement (retour à « À traiter »)", async ({ page }) => {
    const appels = await ouvrirConsole(page, { "GET /taches": (_a, route) => json(route, { count: 0, next: null, previous: null, results: [] }) }, MOI_COMPLET);
    await page.goto("/console/journal");
    await expect(page).toHaveURL(/\/a-traiter$/);
    await expect(page.getByRole("heading", { name: /Bonjour Abdou/ })).toBeVisible();
    expect(appels.some((a) => a.chemin.startsWith("/plateforme"))).toBe(false);
  });

  test("liste avec statistiques, tuiles et recherche côté serveur", async ({ page }) => {
    const recherches: Array<string | null> = [];
    await ouvrirConsole(page, {
      "GET /plateforme/etablissements": (_a, route) => {
        const q = paramsDe(route).get("q");
        recherches.push(q);
        return json(route, ETABLISSEMENTS.filter((e) => !q || e.code.includes(q) || e.raison_sociale.toLowerCase().includes(q.toLowerCase())));
      },
    });
    await page.goto("/console");
    const table = page.getByRole("region", { name: "Établissements" });
    await expect(table.getByRole("row")).toHaveCount(4);
    await expect(table).toContainText("banque-atlantique-sn");
    await expect(table.getByRole("row", { name: /SFD Kaolack/ })).toContainText("Lecture seule");
    await expect(table.getByRole("row", { name: /SFD Kaolack/ })).toContainText("Rompue");
    await expect(table.getByRole("row", { name: /Sow & Fils/ })).toContainText("Non contrôlée");
    await expect(table.getByRole("row", { name: /Banque Atlantique/ })).toContainText("+ 2 invités");
    const tuiles = page.getByRole("region", { name: "Indicateurs" });
    await expect(tuiles).toContainText("57"); // 48 + 9 + 0 utilisateurs actifs

    await page.getByLabel("Rechercher un établissement").fill("kaolack");
    await expect(table.getByRole("row")).toHaveCount(2);
    expect(recherches).toContain("kaolack");
    await expect(tuiles).toContainText("57"); // les tuiles ne dépendent pas de la recherche

    await page.getByLabel("Rechercher un établissement").fill("zzz");
    await expect(page.getByText("Aucun établissement ne correspond à cette recherche.")).toBeVisible();
  });

  test("provisionnement : code_totp envoyé, puis ouverture de la fiche", async ({ page }) => {
    const nouveau = detail(9, { code: "banque-du-sahel", raison_sociale: "Banque du Sahel" });
    const appels = await ouvrirConsole(page, {
      "POST /plateforme/etablissements": (_a, route) =>
        json(route, { ...nouveau, administrateur: { id: "u1", email: "awa.diop@sahel.sn", prenom: "Awa", nom: "Diop", statut: "INVITE" } }, 201),
      [`GET /plateforme/etablissements/${nouveau.id}`]: (_a, route) => json(route, nouveau),
    });
    await page.goto("/console");
    const d = await remplirCreation(page);
    const creer = d.getByRole("button", { name: "Créer l'établissement" });
    await expect(creer).toBeDisabled();
    await saisirOtp(page, "123456");
    await expect(creer).toBeEnabled();
    await creer.click();

    await expect(page).toHaveURL(new RegExp(`/console/etablissements/${nouveau.id}$`));
    await expect(page.getByRole("heading", { name: "Banque du Sahel", level: 1 })).toBeVisible();
    const post = appels.find((a) => a.methode === "POST" && a.chemin === "/plateforme/etablissements");
    expect(post?.corps).toEqual({
      code: "banque-du-sahel",
      raison_sociale: "Banque du Sahel",
      type: "BANQUE",
      pays: "SN",
      administrateur: { email: "awa.diop@sahel.sn", prenom: "Awa", nom: "Diop" },
      code_totp: "123456",
    });
    expect(post?.csrf).toBe("jeton-csrf-test");
  });

  test("conflits 409 : CODE_EXISTE sous le code, EMAIL_EXISTE sous l'adresse, le code TOTP reste saisi", async ({ page }) => {
    let conflit = "CODE_EXISTE";
    const appels = await ouvrirConsole(page, {
      "POST /plateforme/etablissements": (_a, route) => erreur(route, 409, conflit, "Conflit."),
    });
    await page.goto("/console");
    const d = await remplirCreation(page, { code: "sfd-kaolack" });
    await saisirOtp(page, "123456");
    await d.getByRole("button", { name: "Créer l'établissement" }).click();
    await expect(d.getByText("Ce code est déjà utilisé par un autre établissement.")).toBeVisible();
    await expect(d.getByLabel(/^Code de l'établissement/)).toHaveAttribute("aria-invalid", "true");
    await expect(d).toBeVisible();

    conflit = "EMAIL_EXISTE";
    await d.getByLabel(/^Code de l'établissement/).fill("sfd-kaolack-2");
    await expect(d.getByRole("button", { name: "Créer l'établissement" })).toBeEnabled();
    await d.getByRole("button", { name: "Créer l'établissement" }).click();
    await expect(d.getByText("Cette adresse e-mail est déjà utilisée sur la plateforme.")).toBeVisible();
    expect(appels.filter((a) => a.methode === "POST")).toHaveLength(2);
  });

  test("code TOTP refusé : message sous les cases, fenêtre conservée", async ({ page }) => {
    await ouvrirConsole(page, { "POST /plateforme/etablissements": (_a, route) => erreur(route, 401, "CODE_INVALIDE", "Code invalide.") });
    await page.goto("/console");
    const d = await remplirCreation(page);
    await saisirOtp(page, "000000");
    await d.getByRole("button", { name: "Créer l'établissement" }).click();
    await expect(d.getByText(/Code invalide ou expiré/)).toBeVisible();
    await expect(page).toHaveURL(/\/console$/);
  });

  test("fiche : modification, invitation d'un administrateur (code) et conflit EMAIL_EXISTE", async ({ page }) => {
    const e = detail(1, { code: "banque-atlantique-sn", raison_sociale: "Banque Atlantique Sénégal" });
    let invitationRefusee = true;
    const appels = await ouvrirConsole(page, {
      [`GET /plateforme/etablissements/${e.id}`]: (_a, route) => json(route, e),
      [`PATCH /plateforme/etablissements/${e.id}`]: (a, route) => json(route, { ...e, raison_sociale: (a.corps as { raison_sociale: string }).raison_sociale }),
      [`POST /plateforme/etablissements/${e.id}/administrateurs`]: (_a, route) =>
        invitationRefusee
          ? erreur(route, 409, "EMAIL_EXISTE", "Adresse déjà utilisée.")
          : json(route, { id: "u2", email: "nouveau@banque.sn", prenom: "Omar", nom: "Ba", statut: "INVITE" }, 201),
    });
    await page.goto(`/console/etablissements/${e.id}`);
    await expect(page.getByRole("heading", { name: "Banque Atlantique Sénégal", level: 1 })).toBeVisible();
    await expect(page.getByText("Seuls des compteurs sont visibles")).toBeVisible();

    await page.getByRole("button", { name: "Modifier", exact: true }).click();
    const m = page.getByRole("dialog", { name: "Modifier l'établissement" });
    await m.getByLabel(/^Raison sociale/).fill("Atlantique SA");
    await saisirOtp(page, "111111");
    await m.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByRole("heading", { name: "Atlantique SA", level: 1 })).toBeVisible();
    expect(appels.find((a) => a.methode === "PATCH")?.corps).toEqual({ raison_sociale: "Atlantique SA", code: "111111" });

    await page.getByRole("button", { name: "Inviter un administrateur" }).click();
    const i = page.getByRole("dialog", { name: "Inviter un administrateur" });
    await i.getByLabel(/^Prénom/).fill("Omar");
    await i.getByLabel(/^Nom/).fill("Ba");
    await i.getByLabel(/^Adresse e-mail/).fill("nouveau@banque.sn");
    await saisirOtp(page, "222222");
    await i.getByRole("button", { name: "Inviter", exact: true }).click();
    await expect(i.getByText("Cette adresse e-mail est déjà utilisée sur la plateforme.")).toBeVisible();
    invitationRefusee = false;
    await i.getByLabel(/^Adresse e-mail/).fill("nouveau@banque.sn ");
    await i.getByRole("button", { name: "Inviter", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const posts = appels.filter((a) => a.chemin.endsWith("/administrateurs"));
    expect(posts.at(-1)?.corps).toEqual({ prenom: "Omar", nom: "Ba", email: "nouveau@banque.sn", code: "222222" });
  });

  test("P4 : réinitialisation de l'Authenticator avec la référence de la demande", async ({ page }) => {
    const e = detail(1);
    let refus = true;
    const appels = await ouvrirConsole(page, {
      [`GET /plateforme/etablissements/${e.id}`]: (_a, route) => json(route, e),
      [`POST /plateforme/etablissements/${e.id}/reinitialisation-authenticator`]: (_a, route) =>
        refus
          ? erreur(route, 409, "AUTRE_ADMINISTRATEUR_DISPONIBLE", "Un autre administrateur actif peut traiter ce cas.")
          : json(route, { signalement_id: "s1", statut: "REINITIALISE", traite_le: "2026-10-19T09:00:00Z" }),
    });
    await page.goto(`/console/etablissements/${e.id}`);
    await page.getByRole("button", { name: /Réinitialiser l'Authenticator/ }).click();
    const d = page.getByRole("dialog", { name: "Réinitialiser l'Authenticator" });
    const bouton = d.getByRole("button", { name: "Réinitialiser", exact: true });
    await d.getByLabel(/^Adresse e-mail de l'administrateur/).fill("dg@banque.sn");
    await saisirOtp(page, "333333");
    await expect(bouton).toBeDisabled(); // la référence de la demande est obligatoire
    await d.getByLabel(/^Référence de la demande/).fill("COURRIER-2026-114");
    await d.getByLabel("Commentaire").fill("Appel vidéo avec CNI le 19/10/2026");
    await bouton.click();
    await expect(d.getByRole("alert")).toContainText("Un autre administrateur actif peut traiter ce cas.");
    refus = false;
    await saisirOtp(page, "444444");
    await bouton.click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText("Authenticator réinitialisé")).toBeVisible();
    const posts = appels.filter((a) => a.chemin.endsWith("/reinitialisation-authenticator"));
    expect(posts.at(-1)?.corps).toEqual({
      email: "dg@banque.sn",
      reference_demande: "COURRIER-2026-114",
      commentaire: "Appel vidéo avec CNI le 19/10/2026",
      code: "444444",
    });
  });

  test("suspension : boutons masqués quand le réglage est coupé", async ({ page }) => {
    const e = detail(1, { suspension_manuelle_disponible: false });
    await ouvrirConsole(page, { [`GET /plateforme/etablissements/${e.id}`]: (_a, route) => json(route, e) });
    await page.goto(`/console/etablissements/${e.id}`);
    await expect(page.getByRole("heading", { name: e.raison_sociale, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Changer le statut" })).toHaveCount(0);
    await expect(page.getByText(/La suspension manuelle n'est pas activée/)).toBeVisible();
  });

  test("suspension disponible : changement de statut avec motif, puis 403 SUSPENSION_MANUELLE_DESACTIVEE masque les boutons", async ({ page }) => {
    const e = detail(1, { suspension_manuelle_disponible: true });
    let coupe = false;
    const appels = await ouvrirConsole(page, {
      [`GET /plateforme/etablissements/${e.id}`]: (_a, route) => json(route, e),
      [`PATCH /plateforme/etablissements/${e.id}`]: (a, route) =>
        coupe
          ? erreur(route, 403, "SUSPENSION_MANUELLE_DESACTIVEE", "La suspension manuelle est désactivée.")
          : json(route, { ...e, statut: (a.corps as { statut: string }).statut }),
    });
    await page.goto(`/console/etablissements/${e.id}`);
    await page.getByRole("button", { name: "Changer le statut" }).click();
    let d = page.getByRole("dialog", { name: "Changer le statut" });
    await d.getByLabel("Nouveau statut").selectOption("SUSPENDU");
    await saisirOtp(page, "555555");
    await expect(d.getByRole("button", { name: "Appliquer" })).toBeDisabled(); // motif obligatoire
    await d.getByLabel(/^Motif/).fill("Impayé de plus de 90 jours");
    await d.getByRole("button", { name: "Appliquer" }).click();
    await expect(page.getByText("Suspendu", { exact: true }).first()).toBeVisible();
    expect(appels.find((a) => a.methode === "PATCH")?.corps).toEqual({ statut: "SUSPENDU", motif: "Impayé de plus de 90 jours", code: "555555" });

    coupe = true;
    await page.getByRole("button", { name: "Changer le statut" }).click();
    d = page.getByRole("dialog", { name: "Changer le statut" });
    await d.getByLabel("Nouveau statut").selectOption("ACTIF");
    await d.getByLabel(/^Motif/).fill("Régularisation");
    await saisirOtp(page, "666666");
    await d.getByRole("button", { name: "Appliquer" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Changer le statut" })).toHaveCount(0);
  });

  test("journal de la plateforme : liste, curseur et filtres", async ({ page }) => {
    const urls: URL[] = [];
    await ouvrirConsole(page, {
      "GET /plateforme/audit": (_a, route) => {
        const u = new URL(route.request().url());
        urls.push(u);
        if (u.searchParams.get("curseur") === "page2") return json(route, { next: null, results: [evenement(2, { acteur_libelle: "Super-admin FYXOP", detail: "Seconde page" })] });
        return json(route, {
          next: `${ORIGINE}/api/v1/plateforme/audit?curseur=page2&periode=30j&taille=50`,
          results: [evenement(1, { action_libelle: "Établissement créé", objet_libelle: "banque-du-sahel", detail: "Provisionnement" })],
        });
      },
    });
    await page.goto("/console/journal");
    await expect(page.getByRole("heading", { name: "Journal de la plateforme" })).toBeVisible();
    const table = page.getByRole("region", { name: "Événements du journal de la plateforme" });
    await expect(table).toContainText("Établissement créé");
    await expect(table).toContainText("Seconde page");
    expect(urls[0]?.pathname).toBe("/api/v1/plateforme/audit");
    expect(urls[0]?.searchParams.get("periode")).toBe("30j");
    await expect(page.getByText(/Fin du journal · 2 événements/)).toBeVisible();

    await page.getByLabel("Rechercher dans le journal").fill("sahel");
    await expect.poll(() => urls.some((u) => u.searchParams.get("q") === "sahel")).toBe(true);
    await expect(menu(page).getByRole("link", { name: "Journal de la plateforme" })).toHaveAttribute("aria-current", "page");
  });

  test("fiche introuvable : message et retour à la liste", async ({ page }) => {
    await ouvrirConsole(page, {
      "GET /plateforme/etablissements/aaaaaaaa-0000-4000-8000-0000000000ff": (_a, route) => erreur(route, 404, "INTROUVABLE", "Établissement introuvable."),
    });
    await page.goto("/console/etablissements/aaaaaaaa-0000-4000-8000-0000000000ff");
    await expect(page.getByText("Établissement introuvable", { exact: true }).first()).toBeVisible();
    await page.getByRole("link", { name: "← Tous les établissements" }).click();
    await expect(page).toHaveURL(/\/console$/);
  });
});

// Sert à éviter les avertissements d'imports inutilisés si les données évoluent.
void MOI;
void moiAvec;
void etablissement;
