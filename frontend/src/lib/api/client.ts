/**
 * Client d'API ALPHA (architecture § 7.4).
 *
 * - `fetch` avec `credentials: "include"` : session par cookie httpOnly
 *   `alpha_sid`, même origine (rewrites Next en dev, Caddy en recette/prod) ;
 * - en-tête `X-CSRFToken` (cookie `alpha_csrf`) pour toute méthode non sûre ;
 *   cookie absent → `GET /auth/csrf` d'abord ; refus CSRF_INVALIDE → un seul
 *   nouvel essai avec un jeton neuf ;
 * - toute erreur `{code, message, details}` devient une `ApiError` ;
 * - 401 SESSION_EXPIREE → redirection vers `/connexion?suivant=<route>` ;
 * - 403 PERMISSION_REFUSEE → `ApiError` avec `estAccesRefuse`, que la page
 *   appelante affiche (« Accès refusé ») ;
 * - `fond: true` ajoute `X-Alpha-Fond: 1` : l'appel ne prolonge pas l'inactivité.
 *
 * À n'utiliser que dans des composants client : aucun secret côté serveur Next.
 */
import { assurerJetonCsrf, ENTETE_CSRF } from "./csrf";
import { ApiError, erreurDepuisReponse, erreurReseau } from "./erreurs";

export const BASE_API = "/api/v1";
export const ENTETE_FOND = "X-Alpha-Fond";

export type Methode = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type ValeurParam = string | number | boolean | null | undefined;
export type Params = Record<string, ValeurParam | ValeurParam[]>;

export interface OptionsRequete {
  methode?: Methode;
  /** Objet sérialisé en JSON, ou `FormData` envoyé tel quel. */
  corps?: unknown;
  /** Paramètres de requête (`null`/`undefined` ignorés, tableaux répétés). */
  params?: Params;
  signal?: AbortSignal;
  /** Appel de fond (compteurs, notifications) : `X-Alpha-Fond: 1`. */
  fond?: boolean;
  /** Type de réponse attendu (blob pour l'export Excel du journal). */
  reponse?: "json" | "blob" | "texte";
  /** `false` pour gérer soi-même la session expirée (écrans d'authentification). */
  redirigerSiSessionExpiree?: boolean;
  entetes?: Record<string, string>;
}

const METHODES_SURES = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

/** `/taches` → `/api/v1/taches` ; un chemin commençant par `/api/` est conservé. */
export function construireUrl(chemin: string, params?: Params): string {
  const base = chemin.startsWith("/api/") ? chemin : `${BASE_API}${chemin.startsWith("/") ? "" : "/"}${chemin}`;
  if (!params) return base;
  const recherche = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(params)) {
    for (const v of Array.isArray(valeur) ? valeur : [valeur]) {
      if (v !== null && v !== undefined) recherche.append(cle, String(v));
    }
  }
  const qs = recherche.toString();
  return qs ? `${base}${base.includes("?") ? "&" : "?"}${qs}` : base;
}

let redirectionEnCours = false;

function redirigerVersConnexion(): void {
  if (typeof window === "undefined" || redirectionEnCours) return;
  const { pathname, search } = window.location;
  if (pathname.startsWith("/connexion")) return;
  redirectionEnCours = true;
  // `motif=expiree` : l'écran de connexion affiche « Votre session a expiré ».
  window.location.assign(`/connexion?suivant=${encodeURIComponent(pathname + search)}&motif=expiree`);
}

async function envoyer(url: string, o: OptionsRequete, methode: Methode, forcerCsrf: boolean): Promise<Response> {
  const entetes: Record<string, string> = { Accept: "application/json", ...o.entetes };
  let body: BodyInit | undefined;
  if (o.corps instanceof FormData) {
    body = o.corps;
  } else if (o.corps !== undefined) {
    entetes["Content-Type"] = "application/json";
    body = JSON.stringify(o.corps);
  }
  if (o.fond) entetes[ENTETE_FOND] = "1";
  if (!METHODES_SURES.has(methode)) {
    const jeton = await assurerJetonCsrf(forcerCsrf);
    if (jeton) entetes[ENTETE_CSRF] = jeton;
  }
  try {
    return await fetch(url, { method: methode, headers: entetes, body, credentials: "include", signal: o.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw erreurReseau(e);
  }
}

export async function requeteApi<T = unknown>(chemin: string, options: OptionsRequete = {}): Promise<T> {
  const methode = options.methode ?? "GET";
  const url = construireUrl(chemin, options.params);

  let reponse = await envoyer(url, options, methode, false);
  let erreur = reponse.ok ? null : await erreurDepuisReponse(reponse);

  if (erreur?.code === "CSRF_INVALIDE" && !METHODES_SURES.has(methode)) {
    reponse = await envoyer(url, options, methode, true);
    erreur = reponse.ok ? null : await erreurDepuisReponse(reponse);
  }

  if (erreur) {
    if (erreur.estSessionExpiree && options.redirigerSiSessionExpiree !== false) redirigerVersConnexion();
    throw erreur;
  }

  if (reponse.status === 204 || reponse.status === 205) return undefined as T;
  switch (options.reponse ?? "json") {
    case "blob":
      return (await reponse.blob()) as T;
    case "texte":
      return (await reponse.text()) as T;
    default: {
      const texte = await reponse.text();
      if (!texte) return undefined as T;
      try {
        return JSON.parse(texte) as T;
      } catch (e) {
        const err = new ApiError({
          status: reponse.status,
          code: "REPONSE_INVALIDE",
          message: "Réponse illisible du serveur.",
          requestId: reponse.headers.get("X-Request-ID"),
        });
        (err as Error).cause = e;
        throw err;
      }
    }
  }
}

type SansMethode = Omit<OptionsRequete, "methode" | "corps">;

/** Raccourcis : `api.get<Moi>("/auth/session")`, `api.post("/auth/mfa", { code })`. */
export const api = {
  get: <T = unknown>(chemin: string, o?: SansMethode) => requeteApi<T>(chemin, { ...o, methode: "GET" }),
  post: <T = unknown>(chemin: string, corps?: unknown, o?: SansMethode) =>
    requeteApi<T>(chemin, { ...o, methode: "POST", corps }),
  put: <T = unknown>(chemin: string, corps?: unknown, o?: SansMethode) =>
    requeteApi<T>(chemin, { ...o, methode: "PUT", corps }),
  patch: <T = unknown>(chemin: string, corps?: unknown, o?: SansMethode) =>
    requeteApi<T>(chemin, { ...o, methode: "PATCH", corps }),
  delete: <T = unknown>(chemin: string, o?: SansMethode) => requeteApi<T>(chemin, { ...o, methode: "DELETE" }),
};

export { ApiError };
