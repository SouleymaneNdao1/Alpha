/**
 * Jeton CSRF (architecture § 4.1) : le backend pose le cookie `alpha_csrf`
 * (lisible par JavaScript) via `GET /api/v1/auth/csrf` ; toute méthode non sûre
 * le renvoie dans l'en-tête `X-CSRFToken`.
 */
export const COOKIE_CSRF = "alpha_csrf";
export const ENTETE_CSRF = "X-CSRFToken";
const CHEMIN_CSRF = "/api/v1/auth/csrf";

export function lireCookie(nom: string): string | null {
  if (typeof document === "undefined") return null;
  for (const morceau of document.cookie.split(";")) {
    const [cle, ...valeur] = morceau.trim().split("=");
    if (cle === nom) return decodeURIComponent(valeur.join("="));
  }
  return null;
}

export function lireJetonCsrf(): string | null {
  return lireCookie(COOKIE_CSRF);
}

let enCours: Promise<string | null> | null = null;

/**
 * Renvoie le jeton CSRF, en le demandant au backend s'il n'existe pas encore
 * (ou si `forcer`, après un refus CSRF_INVALIDE). Les appels concurrents
 * partagent la même requête.
 */
export async function assurerJetonCsrf(forcer = false): Promise<string | null> {
  const existant = lireJetonCsrf();
  if (existant && !forcer) return existant;
  enCours ??= fetch(CHEMIN_CSRF, { credentials: "include", headers: { Accept: "application/json" } })
    .then(() => lireJetonCsrf())
    .catch(() => null)
    .finally(() => {
      enCours = null;
    });
  return enCours;
}
