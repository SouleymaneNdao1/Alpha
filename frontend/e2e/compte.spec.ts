import { expect, test } from "@playwright/test";
import { CODES_SECOURS, erreur, json, QR_SVG, saisirOtp } from "./aide";
import { MOI_COMPLET, page as pageDe } from "./donnees";
import { absence, DELEGATAIRES, ouvrirCompte, PREFERENCES, SECURITE, SESSIONS } from "./donnees-f67";

test.describe("Mon compte (F6)", () => {
  test("quatre onglets, onglet demandé par l'URL, profil et enregistrement", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "PATCH /moi": (a, route) => json(route, { ...MOI_COMPLET, ...a.corps }),
    });
    await page.goto("/mon-compte");
    await expect(page.getByRole("heading", { name: "Mon compte", level: 1 })).toBeVisible();
    await expect(page.getByText("Établissement démo · vos informations, votre sécurité, vos absences et vos notifications.")).toBeVisible();
    const onglets = page.getByRole("tablist", { name: "Mon compte" });
    for (const nom of ["Profil", "Sécurité", "Absences et délégation", "Notifications"]) {
      await expect(onglets.getByRole("tab", { name: nom })).toBeVisible();
    }
    // Profil
    await expect(page.getByLabel("Prénom")).toHaveValue("Abdou");
    await expect(page.getByLabel("Nom", { exact: true })).toHaveValue("Kane");
    await expect(page.getByLabel("E-mail professionnel")).toHaveAttribute("readonly", "");
    await expect(page.getByText("Le rôle et le périmètre sont attribués par l’administrateur.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enregistrer" })).toBeDisabled();

    await page.getByLabel("Téléphone mobile").fill("0770000000");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Format international attendu")).toBeVisible();
    await page.getByLabel("Téléphone mobile").fill("+221770000000");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Profil enregistré")).toBeVisible();
    const patch = appels.find((a) => a.methode === "PATCH" && a.chemin === "/moi");
    expect(patch?.corps).toMatchObject({ prenom: "Abdou", nom: "Kane", telephone_mobile: "+221770000000" });

    // L'onglet de l'URL est respecté, et un clic le met à jour.
    await page.goto("/mon-compte?onglet=notifications");
    await expect(onglets.getByRole("tab", { name: "Notifications", selected: true })).toBeVisible();
    await onglets.getByRole("tab", { name: "Sécurité" }).click();
    await expect(page).toHaveURL(/onglet=securite/);
  });

  test("sécurité : état, sessions, déconnexion d'un appareil et des autres", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "DELETE /moi/sessions/aaaaaaaa-0000-4000-8000-000000000002": (_a, route) => route.fulfill({ status: 204 }),
      "POST /moi/sessions/revoquer-autres": (_a, route) => json(route, { revoquees: 1 }),
    });
    await page.goto("/mon-compte?onglet=securite");
    await expect(page.getByText("7 sur 10")).toBeVisible();
    await expect(page.getByText("Activée")).toBeVisible();
    const table = page.getByRole("region", { name: "Appareils et sessions actives" });
    await expect(table).toContainText("Chrome sur Windows");
    await expect(table.getByText("Cette session")).toBeVisible();
    await expect(table.getByRole("button", { name: /Déconnecter : Chrome/ })).toHaveCount(0);
    await table.getByRole("button", { name: "Déconnecter : Safari sur iPhone" }).click();
    await expect(page.getByText("Session fermée")).toBeVisible();
    expect(appels.some((a) => a.methode === "DELETE" && a.chemin.endsWith("0002"))).toBe(true);
    await page.getByRole("button", { name: "Déconnecter les autres appareils" }).click();
    await expect.poll(() => appels.some((a) => a.chemin === "/moi/sessions/revoquer-autres")).toBe(true);
  });

  test("changement de mot de passe : règles, code Authenticator, code refusé puis accepté", async ({ page }) => {
    let essais = 0;
    const appels = await ouvrirCompte(page, {
      "POST /moi/mot-de-passe": (_a, route) => {
        essais += 1;
        return essais === 1 ? erreur(route, 401, "CODE_INVALIDE", "Code invalide.", { tentatives_restantes: 4 }) : route.fulfill({ status: 204 });
      },
    });
    await page.goto("/mon-compte?onglet=securite");
    await page.getByRole("button", { name: "Changer le mot de passe" }).click();
    const fenetre = page.getByRole("dialog", { name: "Changer le mot de passe" });
    await expect(fenetre).toBeVisible();
    const valider = fenetre.getByRole("button", { name: "Changer le mot de passe" });
    await expect(valider).toBeDisabled();

    await fenetre.getByLabel("Mot de passe actuel").fill("AncienMdp!2026");
    await fenetre.getByLabel("Nouveau mot de passe").fill("court");
    await fenetre.getByLabel("Confirmer le mot de passe").fill("autre");
    await expect(fenetre.getByText("Les deux mots de passe ne sont pas identiques.")).toBeVisible();
    await fenetre.getByLabel("Nouveau mot de passe").fill("NouveauMdp!2026x");
    await fenetre.getByLabel("Confirmer le mot de passe").fill("NouveauMdp!2026x");
    await saisirOtp(page, "111111");
    await expect(valider).toBeEnabled();
    await valider.click();
    await expect(fenetre.getByText(/Code invalide ou expiré\..*Il vous reste 4 essais/)).toBeVisible();

    await saisirOtp(page, "222222");
    await valider.click();
    await expect(page.getByText("Mot de passe modifié")).toBeVisible();
    await expect(fenetre).toBeHidden();
    const envois = appels.filter((a) => a.chemin === "/moi/mot-de-passe");
    expect(envois).toHaveLength(2);
    expect(envois[1]!.corps).toEqual({ actuel: "AncienMdp!2026", nouveau: "NouveauMdp!2026x", confirmation: "NouveauMdp!2026x", code: "222222" });
  });

  test("changement d'Authenticator en deux étapes (code actuel, QR, premier code du nouveau)", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "POST /moi/authenticator/changement": (_a, route) =>
        json(route, { qr_svg: QR_SVG, secret_affichable: "JBSW Y3DP EHPK 3PXP", emetteur: "ALPHA (Établissement démo)", compte: "a.kane@etablissement-demo.sn" }),
      "POST /moi/authenticator/changement/confirmer": (_a, route) => route.fulfill({ status: 204 }),
    });
    await page.goto("/mon-compte?onglet=securite");
    await page.getByRole("button", { name: "Changer de téléphone" }).click();
    const fenetre = page.getByRole("dialog", { name: "Changer de téléphone" });
    await expect(fenetre).toContainText("Étape 1 sur 2");
    await saisirOtp(page, "123456");
    await fenetre.getByRole("button", { name: "Continuer" }).click();

    await expect(fenetre).toContainText("Étape 2 sur 2");
    await expect(fenetre.getByLabel("Clé secrète")).toHaveText("JBSW Y3DP EHPK 3PXP");
    await expect(fenetre.getByRole("img", { name: /QR code de la nouvelle application/ })).toBeVisible();
    await saisirOtp(page, "654321");
    await fenetre.getByRole("button", { name: "Activer le nouveau téléphone" }).click();
    await expect(page.getByText("Nouveau téléphone activé")).toBeVisible();
    await expect(fenetre).toBeHidden();
    expect(appels.find((a) => a.chemin === "/moi/authenticator/changement")?.corps).toEqual({ code_actuel: "123456" });
    expect(appels.find((a) => a.chemin === "/moi/authenticator/changement/confirmer")?.corps).toEqual({ code_nouveau: "654321" });
  });

  test("codes de secours : code requis, affichés une seule fois, copie et téléchargement", async ({ page }) => {
    await ouvrirCompte(page, { "POST /moi/codes-secours": (_a, route) => json(route, { codes_secours: CODES_SECOURS }) });
    await page.goto("/mon-compte?onglet=securite");
    await page.getByRole("button", { name: "Régénérer" }).click();
    const fenetre = page.getByRole("dialog", { name: "Régénérer les codes de secours" });
    await saisirOtp(page, "123456");
    await fenetre.getByRole("button", { name: "Régénérer" }).click();

    const codes = page.getByRole("dialog", { name: "Vos nouveaux codes de secours" });
    await expect(codes.getByRole("list", { name: "Codes de secours" }).getByRole("listitem")).toHaveCount(10);
    await expect(codes.getByRole("button", { name: "Terminer" })).toBeDisabled();
    const telechargement = page.waitForEvent("download");
    await codes.getByRole("button", { name: "Télécharger" }).click();
    expect((await telechargement).suggestedFilename()).toBe("alpha-codes-de-secours.txt");
    await expect(codes.getByRole("button", { name: "Copier" })).toBeVisible();
    await codes.getByLabel("J’ai conservé mes codes").check();
    await codes.getByRole("button", { name: "Terminer" }).click();
    await expect(page.getByText(CODES_SECOURS[0]!)).toHaveCount(0);
  });

  test("« J'ai perdu mon téléphone » : confirmation explicite puis retour à la connexion", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "POST /moi/telephone-perdu": (_a, route) => json(route, { message: "Signalement enregistré : la signature est bloquée." }, 202),
    });
    await page.goto("/mon-compte?onglet=securite");
    await page.getByRole("button", { name: "J’ai perdu mon téléphone" }).click();
    const fenetre = page.getByRole("dialog", { name: "J'ai perdu mon téléphone" });
    const signaler = fenetre.getByRole("button", { name: "Signaler la perte" });
    await expect(signaler).toBeDisabled();
    await fenetre.getByLabel("Je confirme avoir perdu mon téléphone").check();
    await signaler.click();
    await expect(page.getByRole("dialog", { name: "Signalement enregistré" })).toContainText("la signature est bloquée");
    await expect(page.getByRole("button", { name: "Retour à la connexion" })).toBeVisible();
    expect(appels.some((a) => a.chemin === "/moi/telephone-perdu")).toBe(true);
  });

  test("absences : demande avec délégataire, pouvoirs insuffisants, chevauchement puis succès", async ({ page }) => {
    let liste: unknown[] = [];
    let essais = 0;
    const appels = await ouvrirCompte(page, {
      "GET /moi/absences": (_a, route) => json(route, pageDe(liste)),
      "POST /moi/absences": (_a, route) => {
        essais += 1;
        if (essais === 1) return erreur(route, 409, "CHEVAUCHEMENT", "Chevauchement.");
        liste = [absence("SOUMISE")];
        return json(route, absence("SOUMISE"), 201);
      },
    });
    await page.goto("/mon-compte?onglet=absences");
    await expect(page.getByText("Aucune demande d’absence pour le moment.")).toBeVisible();
    await expect(page.getByText("Aucune délégation reçue.")).toBeVisible();

    await page.getByRole("button", { name: "Soumettre la demande" }).click();
    await expect(page.getByText("Indiquez le premier jour d'absence.")).toBeVisible();

    await page.getByLabel(/^Du\b/).fill("2026-11-02");
    await page.getByLabel(/^Au\b/).fill("2026-11-06");
    await page.getByLabel("Motif", { exact: true }).selectOption("CONGE");
    await page.getByLabel("Commentaire").fill("Congés annuels");
    // Pouvoirs insuffisants : choix impossible.
    await expect(page.getByRole("radio", { name: /Ousseynou Faye/ })).toBeDisabled();
    await expect(page.getByText("Pouvoirs insuffisants")).toBeVisible();
    await page.getByRole("button", { name: "Soumettre la demande" }).click();
    await expect(page.getByText("Choisissez la personne qui vous remplacera.")).toBeVisible();

    await page.getByRole("radio", { name: /Fatou Sarr/ }).check();
    await page.getByRole("button", { name: "Soumettre la demande" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "chevauche une autre absence" })).toBeVisible();

    await page.getByRole("button", { name: "Soumettre la demande" }).click();
    await expect(page.getByText("Demande d'absence envoyée")).toBeVisible();
    const envoi = appels.filter((a) => a.methode === "POST" && a.chemin === "/moi/absences").at(-1)!;
    expect(envoi.corps).toEqual({ debut: "2026-11-02T00:00:00Z", fin: "2026-11-06T23:59:00Z", motif: "CONGE", commentaire: "Congés annuels", delegataire_id: DELEGATAIRES[0]!.id });

    const demandes = page.getByRole("region", { name: "Mes demandes d'absence" });
    await expect(demandes).toContainText("Fatou Sarr");
    await expect(demandes.getByText("Soumise")).toBeVisible();
  });

  test("absences : annulation d'une demande et délégations reçues", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "GET /moi/absences": (_a, route) => json(route, pageDe([absence("VALIDEE"), absence("REFUSEE", { id: "cccccccc-0000-4000-8000-000000000002", motif_refus: "Période de clôture" })])),
      "POST /moi/absences/cccccccc-0000-4000-8000-000000000001/annuler": (_a, route) => json(route, absence("ANNULEE")),
      "GET /moi/delegations-recues": (_a, route) =>
        json(route, [{ id: "d1", delegant: { id: "x", nom: "Awa Diop" }, role: { id: "r", libelle: "DAF" }, debut: "2026-10-15T00:00:00Z", fin: "2026-10-30T23:59:00Z", statut: "ACTIVE", effective: true }]),
    });
    await page.goto("/mon-compte?onglet=absences");
    const demandes = page.getByRole("region", { name: "Mes demandes d'absence" });
    await expect(demandes.getByText("Validée")).toBeVisible();
    await expect(demandes.getByText("Refusée")).toBeVisible();
    await expect(demandes).toContainText("Motif : Période de clôture");
    const recues = page.getByRole("region", { name: "Délégations reçues" });
    await expect(recues).toContainText("Awa Diop");
    await expect(recues.getByText("En vigueur")).toBeVisible();

    await demandes.getByRole("button", { name: /Annuler l'absence du/ }).click();
    const dialogue = page.getByRole("dialog", { name: "Annuler cette absence ?" });
    await dialogue.getByRole("button", { name: "Annuler l’absence" }).click();
    await expect(page.getByText("Absence annulée")).toBeVisible();
    expect(appels.some((a) => a.methode === "POST" && a.chemin.endsWith("/annuler"))).toBe(true);
  });

  test("notifications : préférences, avertissement SMS et enregistrement", async ({ page }) => {
    const appels = await ouvrirCompte(page, {
      "PUT /moi/preferences-notification": (a, route) => json(route, a.corps),
      "GET /moi/notifications": (_a, route) =>
        json(route, { count: 1, next: null, previous: null, non_lues: 1, results: [{ id: "n1", type: "X", titre: "Absence à valider", corps: "Awa Diop", lien: "/absences/abc", lue_le: null, cree_le: "2026-10-19T08:30:00Z" }] }),
    });
    await page.goto("/mon-compte?onglet=notifications");
    await expect(page.getByRole("switch", { name: "E-mail" })).toBeChecked();
    await expect(page.getByRole("switch", { name: "SMS" })).not.toBeChecked();
    await expect(page.getByText("Les alertes de sécurité sont toujours envoyées par e-mail.")).toBeVisible();
    await expect(page.getByText(/Envoi par SMS et notification mobile disponible prochainement/)).toBeVisible();
    await expect(page.getByRole("list").filter({ hasText: "Absence à valider" })).toContainText("Non lue");

    await page.getByRole("switch", { name: "SMS" }).check();
    await page.getByLabel("Heure du résumé").fill("07:30");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Préférences enregistrées")).toBeVisible();
    expect(appels.find((a) => a.methode === "PUT")?.corps).toEqual({ ...PREFERENCES, sms: true, heure_resume: "07:30" });
  });

  test("aucun débordement horizontal sur mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await ouvrirCompte(page, { "GET /moi/securite": (_a, route) => json(route, { ...SECURITE, signalement: null }), "GET /moi/sessions": (_a, route) => json(route, SESSIONS) });
    await page.goto("/mon-compte?onglet=securite");
    await expect(page.getByText("Safari sur iPhone")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });
});
