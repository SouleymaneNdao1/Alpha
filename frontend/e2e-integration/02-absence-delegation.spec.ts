import { COMPTES, expect, seConnecter, test } from "./aide";

/**
 * Parcours 2 : Awa Diop (analyste crédit) déclare une absence et désigne Khady Seck comme
 * délégataire ; l'administrateur valide ; Khady Seck voit alors les tâches d'Awa « par délégation ».
 * Trois personnes, trois contextes de navigation, un seul backend réel.
 */
function jourUtc(decalageJours: number): string {
  return new Date(Date.now() + decalageJours * 86_400_000).toISOString().slice(0, 10);
}

test("absence déclarée, validée par l'administrateur, tâches visibles par délégation", async ({ nouveauContexte }) => {
  const pageDelegataire = await (await nouveauContexte("10.98.0.1")).newPage();
  const pageAbsent = await (await nouveauContexte("10.98.0.2")).newPage();
  const pageAdmin = await (await nouveauContexte("10.98.0.3")).newPage();

  // 0. Avant tout : Khady Seck n'a aucune tâche par délégation.
  await seConnecter(pageDelegataire, COMPTES.delegataire);
  await expect(pageDelegataire).toHaveURL(/\/a-traiter$/);
  await expect(pageDelegataire.getByRole("heading", { name: /Bonjour Khady, voici ce qui vous attend/ })).toBeVisible();
  await expect(pageDelegataire.getByText(/par délégation de/)).toHaveCount(0);

  // 1. Awa Diop déclare son absence (du jour même, pour que la délégation s'applique dès la validation).
  await seConnecter(pageAbsent, COMPTES.absent);
  await expect(pageAbsent).toHaveURL(/\/a-traiter$/);
  await expect(pageAbsent.getByText("SENAGRI SARL · crédit PME")).toBeVisible();
  await pageAbsent.goto("/mon-compte?onglet=absences");
  await pageAbsent.getByLabel(/^Du\b/).fill(jourUtc(0));
  await pageAbsent.getByLabel(/^Au\b/).fill(jourUtc(3));
  await pageAbsent.getByLabel("Motif", { exact: true }).selectOption("CONGE");
  await pageAbsent.getByLabel("Commentaire").fill("Congés annuels (test d'intégration)");
  await pageAbsent.getByRole("radio", { name: /Khady Seck/ }).check();
  await pageAbsent.getByRole("button", { name: "Soumettre la demande" }).click();
  await expect(pageAbsent.getByText("Demande d'absence envoyée")).toBeVisible();
  const demandes = pageAbsent.getByRole("region", { name: "Mes demandes d'absence" });
  await expect(demandes).toContainText("Khady Seck");
  await expect(demandes.getByText("Soumise")).toBeVisible();

  // Tant que l'absence n'est pas validée, la délégation n'est pas en vigueur.
  await pageDelegataire.reload();
  await expect(pageDelegataire.getByText(/par délégation de/)).toHaveCount(0);

  // 2. L'administrateur valide la demande.
  await seConnecter(pageAdmin, COMPTES.admin);
  await expect(pageAdmin).toHaveURL(/\/a-traiter$/);
  await pageAdmin.goto("/administration/delegations");
  const absences = pageAdmin.getByRole("region", { name: /Absences de l'établissement/ });
  await expect(absences.getByRole("row").filter({ hasText: "Awa Diop" })).toContainText("Soumise");
  await pageAdmin.getByRole("button", { name: "Valider l'absence de Awa Diop" }).click();
  await expect(pageAdmin.getByText("Absence validée")).toBeVisible();
  const delegations = pageAdmin.getByRole("region", { name: /Délégations de l'établissement/ });
  await expect(delegations.getByRole("row").filter({ hasText: "Khady Seck" }).filter({ hasText: "Awa Diop" })).toContainText("En vigueur");

  // 3. Khady Seck voit maintenant les tâches personnelles d'Awa, marquées « par délégation ».
  await pageDelegataire.reload();
  const ligne = pageDelegataire.getByRole("listitem").filter({ hasText: "SENAGRI SARL" });
  await expect(ligne).toContainText("par délégation de Awa Diop");
  await expect(pageDelegataire.getByRole("listitem").filter({ hasText: /par délégation de Awa Diop/ })).not.toHaveCount(0);
  // Et la demande d'Awa affiche son nouvel état.
  await pageAbsent.reload();
  await expect(pageAbsent.getByRole("region", { name: "Mes demandes d'absence" }).getByText("Validée", { exact: true })).toBeVisible();
});
