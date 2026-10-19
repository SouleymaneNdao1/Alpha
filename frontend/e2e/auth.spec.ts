import { expect, test, type Page } from "@playwright/test";
import { CODES_SECOURS, erreur, json, MOI, ouvrirSession, QR_SVG, reponseMfaOk, saisirOtp, sessionOk, simulerApi } from "./aide";

const EMAIL = "a.kane@etablissement-demo.sn";
const MDP = "Mot-de-passe-12!";

/** Alerte de la carte (exclut l'annonceur de routes de Next). */
const alerte = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');

async function seConnecter(page: Page, suivant?: string) {
  await page.goto(suivant ? `/connexion?suivant=${encodeURIComponent(suivant)}` : "/connexion");
  await page.getByLabel("Adresse e-mail professionnelle").fill(EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(MDP);
  await page.getByRole("button", { name: "Continuer" }).click();
}

const connexionMfa = (methodes: string[] = ["TOTP", "CODE_SECOURS"]) => (_a: unknown, route: Parameters<typeof json>[0]) =>
  json(route, { etape: "MFA_REQUIS", methodes });

test.describe("Connexion et MFA (F3)", () => {
  test("connexion réussie : mot de passe, code Authenticator, redirection vers « suivant »", async ({ page }) => {
    const appels = await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route, page) => reponseMfaOk(route, page),
      "GET /auth/session": sessionOk,
    });
    await seConnecter(page, "/a-traiter");
    await expect(page.getByRole("heading", { name: "Double authentification" })).toBeVisible();
    await saisirOtp(page, "123456");
    await expect(page).toHaveURL(/\/a-traiter$/);
    await expect(page.getByRole("heading", { name: /Bonjour Abdou/ })).toBeVisible();
    const connexion = appels.find((a) => a.chemin === "/auth/connexion");
    expect(connexion?.corps).toEqual({ email: EMAIL, mot_de_passe: MDP });
    expect(connexion?.csrf).toBe("jeton-csrf-test");
    expect(appels.find((a) => a.chemin === "/auth/mfa")?.corps).toEqual({ code: "123456" });
  });

  test("redirection par défaut vers /a-traiter et refus d'une URL externe", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route, page) => reponseMfaOk(route, page),
      "GET /auth/session": sessionOk,
    });
    await seConnecter(page, "https://evil.example/piege");
    await saisirOtp(page, "123456");
    await expect(page).toHaveURL(/\/a-traiter$/);
  });

  test("mauvais mot de passe : message d'erreur et mot de passe vidé", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": (_a, route) => erreur(route, 401, "IDENTIFIANTS_INVALIDES", "Adresse e-mail ou mot de passe incorrect."),
    });
    await seConnecter(page);
    await expect(alerte(page)).toContainText("Adresse e-mail ou mot de passe incorrect");
    await expect(page.getByLabel("Mot de passe", { exact: true })).toHaveValue("");
    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  });

  test("compte verrouillé à la connexion MFA : durée affichée et retour au mot de passe", async ({ page }) => {
    const jusqua = new Date(Date.now() + 15 * 60_000).toISOString();
    await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route) =>
        erreur(route, 423, "COMPTE_VERROUILLE", "Compte verrouillé.", { jusqua, deblocage_administrateur: false }),
    });
    await seConnecter(page);
    await saisirOtp(page, "000000");
    await expect(alerte(page)).toContainText(/verrouillé pendant (14|15) minutes/);
    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  });

  test("compte verrouillé jusqu'au déblocage par l'administrateur", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route) =>
        erreur(route, 423, "COMPTE_VERROUILLE", "Compte verrouillé.", { jusqua: null, deblocage_administrateur: true }),
    });
    await seConnecter(page);
    await saisirOtp(page, "000000");
    await expect(alerte(page)).toContainText("Contactez votre administrateur");
  });

  test("trop de requêtes à la connexion : délai affiché", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": (_a, route) =>
        erreur(route, 429, "TROP_DE_REQUETES", "Trop de requêtes.", { reessayer_dans_s: 90 }, { "Retry-After": "90" }),
    });
    await seConnecter(page);
    await expect(alerte(page)).toContainText("Réessayez dans 2 minutes");
  });

  test("MFA : code faux (tentatives restantes) puis code juste", async ({ page }) => {
    let essais = 0;
    await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route, page) => {
        essais += 1;
        return essais === 1
          ? erreur(route, 401, "CODE_INVALIDE", "Code invalide.", { tentatives_restantes: 4 })
          : reponseMfaOk(route, page);
      },
      "GET /auth/session": sessionOk,
    });
    await seConnecter(page);
    await saisirOtp(page, "111111");
    await expect(alerte(page)).toContainText("Il vous reste 4 essais");
    await expect(page.getByRole("heading", { name: "Double authentification" })).toBeVisible();
    await saisirOtp(page, "222222");
    await expect(page).toHaveURL(/\/a-traiter$/);
  });

  test("code de secours : bascule, normalisation du format, avertissement s'il en reste peu", async ({ page }) => {
    const appels = await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route, page) => reponseMfaOk(route, page, 1),
      "GET /auth/session": sessionOk,
    });
    await seConnecter(page);
    await page.getByRole("button", { name: "Utiliser un code de secours" }).click();
    await page.getByLabel("Code de secours").fill("ab12cd34");
    await page.getByRole("button", { name: "Valider" }).click();
    await expect(page).toHaveURL(/\/a-traiter$/);
    expect(appels.find((a) => a.chemin === "/auth/mfa")?.corps).toEqual({ code_secours: "AB12-CD34" });
    await expect(page.getByText("Plus que 1 code de secours")).toBeVisible();
  });

  test("TOTP suspendu : seul le code de secours est proposé", async ({ page }) => {
    await simulerApi(page, { "POST /auth/connexion": connexionMfa(["CODE_SECOURS"]) });
    await seConnecter(page);
    await expect(page.getByLabel("Code de secours")).toBeVisible();
    await expect(page.getByRole("button", { name: /application Authenticator/ })).toHaveCount(0);
    await expect(page.getByText("Authenticator est suspendue")).toBeVisible();
  });

  test("pré-authentification expirée : retour au mot de passe avec message", async ({ page }) => {
    await simulerApi(page, {
      "POST /auth/connexion": connexionMfa(),
      "POST /auth/mfa": (_a, route) => erreur(route, 401, "PREAUTH_EXPIREE", "Pré-authentification expirée."),
    });
    await seConnecter(page);
    await saisirOtp(page, "123456");
    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
    await expect(alerte(page)).toContainText("a expiré (5 minutes)");
  });

  test("réenrôlement requis : explication sans champ MFA", async ({ page }) => {
    await simulerApi(page, { "POST /auth/connexion": (_a, route) => json(route, { etape: "REENROLEMENT_REQUIS", methodes: [] }) });
    await seConnecter(page);
    await expect(page.getByRole("heading", { name: "Reconfigurez votre téléphone" })).toBeVisible();
  });
});

test.describe("Mot de passe oublié et réinitialisation (F3)", () => {
  test("mot de passe oublié : message identique quel que soit le compte", async ({ page }) => {
    const appels = await simulerApi(page, { "POST /auth/mot-de-passe/oubli": (_a, route) => route.fulfill({ status: 202 }) });
    await page.goto("/connexion");
    await page.getByRole("link", { name: "Mot de passe oublié ?" }).click();
    await expect(page).toHaveURL(/\/mot-de-passe-oublie$/);
    await page.getByLabel("Adresse e-mail professionnelle").fill(EMAIL);
    await page.getByRole("button", { name: "Envoyer le lien" }).click();
    await expect(page.getByRole("heading", { name: "Vérifiez vos e-mails" })).toBeVisible();
    await expect(page.getByText("Si un compte actif correspond")).toBeVisible();
    expect(appels.find((a) => a.chemin === "/auth/mot-de-passe/oubli")?.corps).toEqual({ email: EMAIL });
  });

  test("réinitialisation avec un code de secours", async ({ page }) => {
    const appels = await simulerApi(page, {
      "GET /auth/mot-de-passe/reinitialisation/jeton-ok": (_a, route) => json(route, { email_masque: "a***@etablissement-demo.sn" }),
      "POST /auth/mot-de-passe/reinitialisation/jeton-ok": (_a, route) => route.fulfill({ status: 204 }),
    });
    await page.goto("/reinitialisation/jeton-ok");
    await expect(page.getByText("a***@etablissement-demo.sn")).toBeVisible();
    await page.getByLabel("Nouveau mot de passe").fill(MDP);
    await page.getByLabel("Confirmer le mot de passe").fill(MDP);
    await page.getByRole("button", { name: "Utiliser un code de secours" }).click();
    await page.getByLabel("Code de secours").fill("ab12cd34");
    await page.getByRole("button", { name: "Enregistrer le mot de passe" }).click();
    await expect(page).toHaveURL(/\/connexion\?motif=mdp-modifie/);
    await expect(page.getByText("Votre mot de passe a été modifié")).toBeVisible();
    expect(appels.find((a) => a.methode === "POST")?.corps).toEqual({
      mot_de_passe: MDP,
      confirmation: MDP,
      code_secours: "AB12-CD34",
    });
  });

  test("lien de réinitialisation expiré", async ({ page }) => {
    await simulerApi(page, {
      "GET /auth/mot-de-passe/reinitialisation/vieux": (_a, route) => erreur(route, 410, "JETON_INVALIDE", "Lien expiré."),
    });
    await page.goto("/reinitialisation/vieux");
    await expect(page.getByRole("heading", { name: "Lien non valide" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Demander un nouveau lien" })).toBeVisible();
  });
});

test.describe("Activation et téléphone perdu (F4)", () => {
  test("activation complète en 3 étapes jusqu'à /a-traiter", async ({ page }) => {
    const appels = await simulerApi(page, {
      "GET /auth/activation/jeton-ok": (_a, route) =>
        json(route, { prenom: "Abdou", etablissement: "Établissement démo", role: "DAF", etape: "INVITE" }),
      "POST /auth/activation/jeton-ok/mot-de-passe": (_a, route) => route.fulfill({ status: 204 }),
      "POST /auth/activation/jeton-ok/authenticator": (_a, route) =>
        json(route, { qr_svg: QR_SVG, secret_affichable: "JBSW Y3DP EHPK 3PXP", emetteur: "ALPHA", compte: EMAIL }),
      "POST /auth/activation/jeton-ok/authenticator/confirmer": (_a, route) => json(route, { codes_secours: CODES_SECOURS }),
      "POST /auth/activation/jeton-ok/terminer": async (_a, route, page) => {
        await ouvrirSession(page);
        await json(route, MOI);
      },
      "GET /auth/session": sessionOk,
    });
    await page.goto("/activation?jeton=jeton-ok");
    await expect(page.getByRole("heading", { name: "Bienvenue, Abdou" })).toBeVisible();

    // Étape 1 : une confirmation différente est refusée côté client, puis le mot de passe est accepté.
    await page.getByLabel("Nouveau mot de passe").fill(MDP);
    await page.getByLabel("Confirmer le mot de passe").fill("autre");
    await page.getByRole("button", { name: "Continuer" }).click();
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toBeVisible();
    await page.getByLabel("Confirmer le mot de passe").fill(MDP);
    await page.getByRole("button", { name: "Continuer" }).click();

    // Étape 2 : QR code et clé.
    await expect(page.getByRole("heading", { name: "Associez votre téléphone" })).toBeVisible();
    await expect(page.getByRole("img", { name: /QR/i })).toBeVisible();
    await expect(page.getByLabel("Clé secrète")).toHaveText("JBSW Y3DP EHPK 3PXP");
    await page.getByRole("button", { name: /Suivant|Continuer/ }).click();

    // Étape 3 : code Authenticator puis codes de secours.
    await expect(page.getByRole("heading", { name: "Vérifiez votre téléphone" })).toBeVisible();
    await saisirOtp(page, "654321");
    await expect(page.getByRole("heading", { name: "Vos codes de secours" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Codes de secours" }).getByRole("listitem")).toHaveCount(10);
    const fin = page.getByRole("button", { name: "Accéder à ALPHA" });
    await expect(fin).toBeDisabled();
    await page.getByLabel("J’ai conservé mes codes").check();
    await fin.click();
    await expect(page).toHaveURL(/\/a-traiter$/);

    const posts = appels.filter((a) => a.methode === "POST").map((a) => a.chemin);
    expect(posts).toEqual([
      "/auth/activation/jeton-ok/mot-de-passe",
      "/auth/activation/jeton-ok/authenticator",
      "/auth/activation/jeton-ok/authenticator/confirmer",
      "/auth/activation/jeton-ok/terminer",
    ]);
    expect(appels.find((a) => a.chemin.endsWith("/mot-de-passe"))?.corps).toEqual({ mot_de_passe: MDP, confirmation: MDP });
    expect(appels.find((a) => a.chemin.endsWith("/confirmer"))?.corps).toEqual({ code: "654321" });
    expect(appels.find((a) => a.chemin.endsWith("/terminer"))?.corps).toEqual({ codes_conserves: true });
  });

  test("activation : lien d'invitation expiré", async ({ page }) => {
    await simulerApi(page, { "GET /auth/activation/vieux": (_a, route) => erreur(route, 410, "JETON_INVALIDE", "Invitation expirée.") });
    await page.goto("/activation?jeton=vieux");
    await expect(page.getByRole("heading", { name: "Lien non valide" })).toBeVisible();
  });

  test("téléphone perdu : signalement puis consignes", async ({ page }) => {
    const appels = await simulerApi(page, { "POST /auth/telephone-perdu": (_a, route) => route.fulfill({ status: 202 }) });
    await page.goto("/activation");
    await page.getByRole("tab", { name: "Téléphone perdu" }).click();
    await expect(page.getByRole("heading", { name: "Téléphone perdu ou volé ?" })).toBeVisible();
    await page.getByLabel("Adresse e-mail professionnelle").fill(EMAIL);
    await page.getByLabel("Mot de passe").fill(MDP);
    await page.getByRole("button", { name: "Signaler la perte" }).click();
    await expect(page.getByRole("heading", { name: "Signalement enregistré" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Se connecter avec un code de secours" })).toBeVisible();
    expect(appels.find((a) => a.chemin === "/auth/telephone-perdu")?.corps).toEqual({ email: EMAIL, mot_de_passe: MDP });
  });

  test("réenrôlement : mot de passe actuel puis QR code", async ({ page }) => {
    await simulerApi(page, {
      "GET /auth/reenrolement/jeton-re": (_a, route) => json(route, { prenom: "Abdou", etablissement: "Établissement démo" }),
      "POST /auth/reenrolement/jeton-re/mot-de-passe": (_a, route) => route.fulfill({ status: 204 }),
      "POST /auth/reenrolement/jeton-re/authenticator": (_a, route) =>
        json(route, { qr_svg: QR_SVG, secret_affichable: "JBSW Y3DP EHPK 3PXP", emetteur: "ALPHA", compte: EMAIL }),
    });
    await page.goto("/reenrolement/jeton-re");
    await expect(page.getByRole("heading", { name: "Bonjour, Abdou" })).toBeVisible();
    await page.getByLabel("Mot de passe actuel").fill(MDP);
    await page.getByRole("button", { name: "Continuer" }).click();
    await expect(page.getByRole("heading", { name: "Associez votre téléphone" })).toBeVisible();
  });
});
