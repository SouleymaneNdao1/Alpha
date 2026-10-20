import { alerte, codeTotp, COMPTES, expect, lienDansCourriel, saisirOtp, seConnecter, test } from "./aide";

/**
 * Parcours 1 : un administrateur invite un utilisateur ; celui-ci active son compte par le lien de
 * l'e-mail (mot de passe, puis Authenticator, puis codes de secours) et arrive sur « À traiter ».
 * Tout est réel : API Django, PostgreSQL (RLS), e-mail écrit dans un dossier, codes TOTP calculés ici.
 */
const EMAIL = "ismaila.tounkara@etablissement-demo.sn";
const MOT_DE_PASSE = "Cumulus-Rouge-58!ab";

test("l'administrateur invite un analyste crédit, qui active son compte et voit ses tâches", async ({ page, nouveauContexte }) => {
  // 1. L'administrateur invite.
  await seConnecter(page, COMPTES.admin);
  await expect(page).toHaveURL(/\/a-traiter$/);
  await page.goto("/administration/utilisateurs");
  await expect(page.getByRole("heading", { name: "Utilisateurs et rôles", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "+ Inviter un utilisateur" }).click();
  const fenetre = page.getByRole("dialog", { name: "Inviter un utilisateur" });
  await fenetre.getByLabel(/^Prénom\b/).fill("Ismaïla");
  await fenetre.getByLabel(/^Nom\b/).fill("Tounkara");
  await fenetre.getByLabel("Adresse e-mail professionnelle").fill(EMAIL);
  await fenetre.getByLabel(/^Rôle\b/).selectOption({ label: "Analyste crédit" });
  await fenetre.getByRole("button", { name: "Envoyer l’invitation" }).click();
  await expect(page.getByText("Invitation envoyée")).toBeVisible();
  await expect(page.getByRole("region", { name: /Utilisateurs de l'établissement/ }).getByRole("row").filter({ hasText: "Tounkara" })).toContainText("Invité");

  // 2. L'invité ouvre le lien reçu par e-mail (contexte vierge : aucun cookie de l'administrateur).
  const jeton = await lienDansCourriel(EMAIL, /./, /\/activation\?jeton=([A-Za-z0-9_-]+)/);
  const contexte = await nouveauContexte("10.99.0.2");
  const invite = await contexte.newPage();
  await invite.goto(`/activation?jeton=${jeton}`);
  await expect(invite.getByRole("heading", { name: "Bienvenue, Ismaïla" })).toBeVisible();

  // Étape 1 : mot de passe (la politique est appliquée par le serveur).
  await invite.getByLabel("Nouveau mot de passe").fill(MOT_DE_PASSE);
  await invite.getByLabel("Confirmer le mot de passe").fill(MOT_DE_PASSE);
  await invite.getByRole("button", { name: "Continuer" }).click();

  // Étape 2 : le QR code et la clé secrète viennent du serveur ; on lit la clé pour calculer les codes.
  await expect(invite.getByRole("heading", { name: "Associez votre téléphone" })).toBeVisible();
  await expect(invite.getByRole("img", { name: /QR/i })).toBeVisible();
  const secret = ((await invite.getByLabel("Clé secrète").textContent()) ?? "").replace(/\s+/g, "");
  expect(secret).toMatch(/^[A-Z2-7]{32}$/);
  await invite.getByRole("button", { name: /Suivant|Continuer/ }).click();

  // Étape 3 : code Authenticator, codes de secours, puis accès à l'application.
  await expect(invite.getByRole("heading", { name: "Vérifiez votre téléphone" })).toBeVisible();
  await saisirOtp(invite, await codeTotp(secret));
  await expect(invite.getByRole("heading", { name: "Vos codes de secours" })).toBeVisible();
  await expect(invite.getByRole("list", { name: "Codes de secours" }).getByRole("listitem")).toHaveCount(10);
  await invite.getByLabel("J’ai conservé mes codes").check();
  await invite.getByRole("button", { name: "Accéder à ALPHA" }).click();

  // 3. Arrivée sur « À traiter » avec les tâches de son rôle.
  await expect(invite).toHaveURL(/\/a-traiter$/);
  await expect(invite.getByRole("heading", { name: /Bonjour Ismaïla, voici ce qui vous attend/ })).toBeVisible();
  const ligne = invite.getByRole("listitem").filter({ hasText: "CR-2026-0425" });
  await expect(ligne).toContainText("Batiplus SA");
  await expect(alerte(invite)).toHaveCount(0);

  // 4. Le lien est à usage unique : le rejouer ne donne plus accès.
  const autre = await nouveauContexte("10.99.0.3");
  const rejeu = await autre.newPage();
  await rejeu.goto(`/activation?jeton=${jeton}`);
  await expect(rejeu.getByRole("heading", { name: "Lien non valide" })).toBeVisible();
});
