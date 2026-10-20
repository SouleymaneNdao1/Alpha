import { acces, alerte, codeTotp, COMPTES, expect, lienDansCourriel, saisirOtp, seConnecter, test } from "./aide";

/**
 * Parcours 3 « téléphone perdu » : l'utilisateur signale la perte (mot de passe), l'administrateur
 * vérifie son identité et réinitialise l'Authenticator (code TOTP de l'administrateur), l'utilisateur
 * reconfigure son téléphone par le lien reçu par e-mail, puis se reconnecte avec le nouveau secret.
 */
test("signalement, réinitialisation par l'administrateur, réenrôlement et reconnexion", async ({ nouveauContexte }) => {
  const email = COMPTES.telephonePerdu;
  const { motDePasse, secret: ancienSecret } = acces(email);
  const pageUtilisateur = await (await nouveauContexte("10.97.0.1")).newPage();
  const pageAdmin = await (await nouveauContexte("10.97.0.2")).newPage();

  // 1. Signalement depuis la page publique, sans être connecté.
  await pageUtilisateur.goto("/activation");
  await pageUtilisateur.getByRole("tab", { name: "Téléphone perdu" }).click();
  await expect(pageUtilisateur.getByRole("heading", { name: "Téléphone perdu ou volé ?" })).toBeVisible();
  await pageUtilisateur.getByLabel("Adresse e-mail professionnelle").fill(email);
  await pageUtilisateur.getByLabel("Mot de passe").fill(motDePasse);
  await pageUtilisateur.getByRole("button", { name: "Signaler la perte" }).click();
  await expect(pageUtilisateur.getByRole("heading", { name: "Signalement enregistré" })).toBeVisible();

  // L'Authenticator est suspendu : à la connexion, seul un code de secours est proposé.
  const pageAncien = await (await nouveauContexte("10.97.0.3")).newPage();
  await pageAncien.goto("/connexion");
  await pageAncien.getByLabel("Adresse e-mail professionnelle").fill(email);
  await pageAncien.getByLabel("Mot de passe", { exact: true }).fill(motDePasse);
  await pageAncien.getByRole("button", { name: "Continuer" }).click();
  await expect(pageAncien.getByText("Authenticator est suspendue")).toBeVisible();
  await expect(pageAncien.getByLabel("Code de secours")).toBeVisible();
  await expect(pageAncien.getByLabel(/^Chiffre 1 sur 6/)).toHaveCount(0);

  // 2. L'administrateur voit le signalement et réinitialise l'accès après vérification d'identité.
  await seConnecter(pageAdmin, COMPTES.admin);
  await expect(pageAdmin).toHaveURL(/\/a-traiter$/);
  await pageAdmin.goto("/administration/securite");
  const signalements = pageAdmin.getByRole("region", { name: "Signalements téléphone perdu" });
  await expect(signalements).toContainText("Ibou Diallo");
  await expect(signalements.getByRole("row").filter({ hasText: "Ibou Diallo" })).toContainText("Ouvert");
  await signalements.getByRole("button", { name: "Réinitialiser l'accès de Ibou Diallo" }).click();
  const fenetre = pageAdmin.getByRole("dialog", { name: "Réinitialiser l'accès de Ibou Diallo" });
  await saisirOtp(pageAdmin, await codeTotp(acces(COMPTES.admin).secret));
  await fenetre.getByLabel(/Vérification d'identité effectuée/).selectOption("VISIO");
  await fenetre.getByLabel("Commentaire").fill("Appel vidéo avec pièce d'identité (test d'intégration)");
  await fenetre.getByRole("button", { name: "Réinitialiser l'accès" }).click();
  await expect(pageAdmin.getByText("Accès réinitialisé")).toBeVisible();
  await expect(signalements.getByRole("row").filter({ hasText: "Ibou Diallo" })).toContainText("Réinitialisé");

  // 3. Réenrôlement par le lien de l'e-mail : mot de passe actuel, nouveau QR code, codes de secours.
  const jeton = await lienDansCourriel(email, /./, /\/reenrolement\/([A-Za-z0-9_-]+)/);
  await pageUtilisateur.goto(`/reenrolement/${jeton}`);
  await expect(pageUtilisateur.getByRole("heading", { name: "Bonjour, Ibou" })).toBeVisible();
  await pageUtilisateur.getByLabel("Mot de passe actuel").fill(motDePasse);
  await pageUtilisateur.getByRole("button", { name: "Continuer" }).click();
  await expect(pageUtilisateur.getByRole("heading", { name: "Associez votre téléphone" })).toBeVisible();
  const nouveauSecret = ((await pageUtilisateur.getByLabel("Clé secrète").textContent()) ?? "").replace(/\s+/g, "");
  expect(nouveauSecret).toMatch(/^[A-Z2-7]{32}$/);
  expect(nouveauSecret).not.toBe(ancienSecret);
  await pageUtilisateur.getByRole("button", { name: /Suivant|Continuer/ }).click();
  await expect(pageUtilisateur.getByRole("heading", { name: "Vérifiez votre téléphone" })).toBeVisible();
  await saisirOtp(pageUtilisateur, await codeTotp(nouveauSecret));
  await expect(pageUtilisateur.getByRole("heading", { name: "Vos codes de secours" })).toBeVisible();
  await pageUtilisateur.getByLabel("J’ai conservé mes codes").check();
  await pageUtilisateur.getByRole("button", { name: "Accéder à ALPHA" }).click();
  await expect(pageUtilisateur).toHaveURL(/\/a-traiter$/);
  await expect(pageUtilisateur.getByRole("heading", { name: /Bonjour Ibou/ })).toBeVisible();

  // 4. Reconnexion avec le nouveau téléphone, dans un navigateur neuf.
  const pageRetour = await (await nouveauContexte("10.97.0.4")).newPage();
  await seConnecter(pageRetour, email, { motDePasse, secret: nouveauSecret });
  await expect(pageRetour).toHaveURL(/\/a-traiter$/);
  await expect(pageRetour.getByRole("heading", { name: /Bonjour Ibou/ })).toBeVisible();
  await expect(alerte(pageRetour)).toHaveCount(0);
});
