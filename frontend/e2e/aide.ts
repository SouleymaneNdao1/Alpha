import type { Page, Request, Route } from "@playwright/test";

/** Utilisateur « Moi » minimal renvoyé par les faux endpoints. */
export const MOI = {
  id: "11111111-1111-4111-8111-111111111111",
  prenom: "Abdou",
  nom: "Kane",
  initiales: "AK",
  email: "a.kane@etablissement-demo.sn",
  telephone_mobile: null,
  langue: "fr",
  etablissement: { id: "22222222-2222-4222-8222-222222222222", raison_sociale: "Établissement démo", type: "BANQUE", statut: "ACTIF" },
  role_principal: { id: "33333333-3333-4333-8333-333333333333", libelle: "DAF", unite: null },
  affectations: [],
  permissions: [],
  modules: ["COMPTE"],
  signature_bloquee: false,
  inactivite_session_min: 15,
  est_super_admin: false,
  mot_de_passe_expire: false,
};

export const QR_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8" fill="#fff"/><path d="M1 1h2v2H1zM5 1h2v2H5zM1 5h2v2H1zM4 4h1v1H4zM6 5h1v2H6z" fill="#000"/></svg>';

export const CODES_SECOURS = ["AB12-CD34", "EF56-GH78", "JK90-LM12", "NP34-QR56", "ST78-UV90", "WX12-YZ34", "AB56-CD78", "EF90-GH12", "JK34-LM56", "NP78-QR90"];

export interface Appel {
  methode: string;
  chemin: string;
  corps: Record<string, unknown> | null;
  csrf: string | null;
}

export function erreur(route: Route, status: number, code: string, message: string, details: unknown = {}, entetes: Record<string, string> = {}) {
  return route.fulfill({ status, contentType: "application/json", headers: entetes, body: JSON.stringify({ code, message, details }) });
}

export function json(route: Route, corps: unknown, status = 200, entetes: Record<string, string> = {}) {
  return route.fulfill({ status, contentType: "application/json", headers: entetes, body: JSON.stringify(corps) });
}

function corpsDe(r: Request): Record<string, unknown> | null {
  try {
    return r.postDataJSON();
  } catch {
    return null;
  }
}

export type Gestionnaire = (appel: Appel, route: Route, page: Page) => Promise<void> | void;

/**
 * Simule `/api/v1/**`. `gestionnaires` est indexé par « METHODE chemin »
 * (chemin sans le préfixe /api/v1). `GET /auth/csrf` pose le cookie et toute
 * requête POST sans `X-CSRFToken` correct reçoit 403 CSRF_INVALIDE, comme le vrai backend.
 */
export async function simulerApi(page: Page, gestionnaires: Record<string, Gestionnaire>): Promise<Appel[]> {
  const appels: Appel[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const chemin = new URL(req.url()).pathname.replace(/^\/api\/v1/, "").replace(/\/$/, "");
    const methode = req.method();
    if (methode === "GET" && chemin === "/auth/csrf") {
      return route.fulfill({ status: 204, headers: { "set-cookie": "alpha_csrf=jeton-csrf-test; Path=/; SameSite=Lax" } });
    }
    const appel: Appel = { methode, chemin, corps: corpsDe(req), csrf: req.headers()["x-csrftoken"] ?? null };
    appels.push(appel);
    if (methode === "POST" && appel.csrf !== "jeton-csrf-test") {
      return erreur(route, 403, "CSRF_INVALIDE", "Jeton CSRF invalide.");
    }
    const g = gestionnaires[`${methode} ${chemin}`];
    if (!g) return erreur(route, 404, "NON_TROUVE", `Non simulé : ${methode} ${chemin}`);
    await g(appel, route, page);
  });
  return appels;
}

/** Réponse 200 de `POST /auth/mfa` : ouvre la session (cookie alpha_sid, lu par le middleware). */
export async function reponseMfaOk(route: Route, page: Page, restants = 8) {
  await ouvrirSession(page);
  return json(route, { utilisateur: MOI, codes_secours_restants: restants });
}

/** Pose le cookie de session que le vrai backend poserait (Playwright ignore le Set-Cookie HttpOnly d'une réponse simulée). */
export function ouvrirSession(page: Page) {
  return page.context().addCookies([{ name: "alpha_sid", value: "session-test", url: "http://localhost:3100" }]);
}

/** Session valide pour la page provisoire /a-traiter. */
export const sessionOk: Gestionnaire = (_a, route) => json(route, MOI);

/** Saisit un code à 6 chiffres dans les 6 cases de OtpInput. */
export async function saisirOtp(page: Page, code: string) {
  await page.getByLabel(/^Chiffre 1 sur 6/).first().click();
  await page.keyboard.type(code);
}
