import { expect, test } from "@playwright/test";
import { json } from "./aide";
import { MOI_COMPLET, page as pageDe } from "./donnees";
import { notification } from "./donnees-f67";
import { ouvrirEtSimuler } from "./donnees";

test.describe("Cloche des notifications (F6)", () => {
  test("compteur, panneau, ouverture d'une notification et « Tout marquer comme lu »", async ({ page }) => {
    let notifs = [notification(1), notification(2), notification(3, { lue_le: "2026-10-19T08:40:00Z", lien: "" })];
    const appels = await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => json(route, pageDe([])),
      "GET /moi/notifications": (_a, route) => json(route, { ...pageDe(notifs), non_lues: notifs.filter((n) => !n.lue_le).length }),
      "POST /moi/notifications/tout-lu": (_a, route) => {
        notifs = notifs.map((n) => ({ ...n, lue_le: "2026-10-19T09:00:00Z" }));
        return route.fulfill({ status: 204 });
      },
      "POST /moi/notifications/ffffffff-0000-4000-8000-000000000001/lue": (_a, route) => {
        notifs = notifs.map((n) => (n.titre === "Notification 1" ? { ...n, lue_le: "2026-10-19T09:00:00Z" } : n));
        return route.fulfill({ status: 204 });
      },
      "GET /absences/cccccccc-0000-4000-8000-000000000001": (_a, route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ code: "INTROUVABLE", message: "x", details: {} }) }),
    });
    await page.goto("/a-traiter");
    await expect(page.getByTestId("compteur-cloche")).toHaveText("2");

    const cloche = page.getByRole("button", { name: "Notifications : 2 non lues" });
    await cloche.click();
    const panneau = page.getByRole("region", { name: "Notifications reçues" });
    await expect(panneau.getByRole("button", { name: /Notification 1/ })).toBeVisible();
    await expect(panneau.getByRole("button", { name: /Non lue : Notification 2/ })).toBeVisible();
    await expect(panneau.getByText("Notification 3", { exact: true })).toBeVisible();

    // Un clic marque la notification lue et ouvre son lien.
    await panneau.getByRole("button", { name: /Notification 1/ }).click();
    await expect(page).toHaveURL(/\/absences\/cccccccc/);
    await expect(page.getByTestId("compteur-cloche")).toHaveText("1");
    expect(appels.some((a) => a.chemin.endsWith("0001/lue"))).toBe(true);

    await page.getByRole("button", { name: "Notifications : 1 non lue" }).click();
    await page.getByRole("button", { name: "Tout marquer comme lu" }).click();
    await expect(page.getByTestId("compteur-cloche")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();
    expect(appels.some((a) => a.methode === "POST" && a.chemin === "/moi/notifications/tout-lu")).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("region", { name: "Notifications reçues" })).toHaveCount(0);
  });

  test("panneau vide et erreur du serveur sans bloquer la cloche", async ({ page }) => {
    await ouvrirEtSimuler(page, MOI_COMPLET, {
      "GET /taches": (_a, route) => json(route, pageDe([])),
      "GET /moi/notifications": (_a, route) => json(route, { ...pageDe([]), non_lues: 0 }),
    });
    await page.goto("/a-traiter");
    await page.getByRole("button", { name: "Notifications", exact: true }).click();
    await expect(page.getByText("Aucune notification.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Tout marquer comme lu" })).toBeDisabled();
    await expect(page.getByRole("link", { name: "Préférences et toutes les notifications" })).toHaveAttribute("href", "/mon-compte?onglet=notifications");
  });
});
