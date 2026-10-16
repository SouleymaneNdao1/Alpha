/**
 * Erreurs de l'API ALPHA (architecture § 5) : le backend répond toujours
 * `{code, message, details}` ; le client les convertit en `ApiError`.
 */

/** Codes génériques renvoyés par le backend (alpha.core.erreurs). */
export const CODES_GENERIQUES = [
  "VALIDATION",
  "REQUETE_INVALIDE",
  "NON_AUTHENTIFIE",
  "PERMISSION_REFUSEE",
  "CSRF_INVALIDE",
  "INTROUVABLE",
  "METHODE_NON_AUTORISEE",
  "FORMAT_NON_ACCEPTABLE",
  "TYPE_CONTENU_NON_SUPPORTE",
  "TROP_DE_REQUETES",
  "ERREUR_INTERNE",
] as const;

/** Codes métier définis par le contrat d'API (architecture § 4 et 5). */
export const CODES_METIER = [
  "SESSION_EXPIREE",
  "IDENTIFIANTS_INVALIDES",
  "ETABLISSEMENT_SUSPENDU",
  "CODE_INVALIDE",
  "PREAUTH_EXPIREE",
  "COMPTE_VERROUILLE",
  "ETAPE_INVALIDE",
  "JETON_INVALIDE",
  "ROLE_HORS_CATALOGUE",
  "ROLE_SYSTEME",
  "EMAIL_EXISTE",
  "LIBELLE_EXISTE",
  "DERNIER_ADMINISTRATEUR",
  "AUTO_TRAITEMENT_INTERDIT",
  "SIGNATURE_BLOQUEE",
  "CHEVAUCHEMENT",
  "LECTURE_SEULE",
] as const;

/** Codes produits par le client lui-même (aucune réponse exploitable du serveur). */
export const CODES_CLIENT = ["RESEAU_INDISPONIBLE", "REPONSE_INVALIDE"] as const;

export type CodeErreurConnu =
  | (typeof CODES_GENERIQUES)[number]
  | (typeof CODES_METIER)[number]
  | (typeof CODES_CLIENT)[number];

/** Un code inconnu reste possible (nouvelle erreur côté serveur). */
export type CodeErreur = CodeErreurConnu | (string & {});

/** Erreurs de validation : `{"champ": ["message", …]}` (et `non_field_errors`). */
export type DetailsValidation = Record<string, string[]>;

export interface CorpsErreur {
  code: string;
  message: string;
  details?: unknown;
}

/** Messages de repli si le corps de la réponse n'est pas au format ALPHA. */
const REPLI_PAR_STATUT: Record<number, [CodeErreurConnu, string]> = {
  400: ["REQUETE_INVALIDE", "La requête est mal formée."],
  401: ["NON_AUTHENTIFIE", "Vous devez être connecté pour effectuer cette action."],
  403: ["PERMISSION_REFUSEE", "Vous n'avez pas les droits nécessaires pour effectuer cette action."],
  404: ["INTROUVABLE", "La ressource demandée est introuvable."],
  405: ["METHODE_NON_AUTORISEE", "Cette méthode n'est pas autorisée sur cette ressource."],
  406: ["FORMAT_NON_ACCEPTABLE", "Le format de réponse demandé n'est pas disponible."],
  415: ["TYPE_CONTENU_NON_SUPPORTE", "Le type de contenu envoyé n'est pas pris en charge."],
  429: ["TROP_DE_REQUETES", "Trop de tentatives. Patientez avant de réessayer."],
};

export class ApiError extends Error {
  override readonly name = "ApiError";
  /** Statut HTTP (0 si le serveur n'a pas pu être joint). */
  readonly status: number;
  readonly code: CodeErreur;
  readonly details: unknown;
  /** Identifiant de corrélation (en-tête X-Request-ID), utile au support. */
  readonly requestId: string | null;

  constructor(init: { status: number; code: CodeErreur; message: string; details?: unknown; requestId?: string | null }) {
    super(init.message);
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
  }

  get estValidation(): boolean {
    return this.code === "VALIDATION";
  }

  get estSessionExpiree(): boolean {
    return this.status === 401 && this.code === "SESSION_EXPIREE";
  }

  get estAccesRefuse(): boolean {
    return this.status === 403 && this.code === "PERMISSION_REFUSEE";
  }

  /** Erreurs par champ pour un code VALIDATION (sinon objet vide). */
  get erreursDeChamps(): DetailsValidation {
    if (!this.estValidation || !estObjet(this.details)) return {};
    const resultat: DetailsValidation = {};
    for (const [champ, valeur] of Object.entries(this.details)) {
      resultat[champ] = Array.isArray(valeur) ? valeur.map(String) : [String(valeur)];
    }
    return resultat;
  }
}

export function estApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

function estObjet(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function estCorpsErreur(v: unknown): v is CorpsErreur {
  return estObjet(v) && typeof v.code === "string" && typeof v.message === "string";
}

/** Convertit une réponse HTTP en échec en `ApiError`. */
export async function erreurDepuisReponse(reponse: Response): Promise<ApiError> {
  const requestId = reponse.headers.get("X-Request-ID");
  let corps: unknown = null;
  try {
    corps = await reponse.json();
  } catch {
    // Corps vide ou non JSON (page HTML d'un proxy, 502…) : repli ci-dessous.
  }
  if (estCorpsErreur(corps)) {
    return new ApiError({ status: reponse.status, code: corps.code, message: corps.message, details: corps.details, requestId });
  }
  const [code, message] =
    REPLI_PAR_STATUT[reponse.status] ??
    (reponse.status >= 500
      ? (["ERREUR_INTERNE", "Une erreur inattendue s'est produite. Réessayez plus tard."] as const)
      : (["REPONSE_INVALIDE", `Réponse inattendue du serveur (HTTP ${reponse.status}).`] as const));
  return new ApiError({ status: reponse.status, code, message, requestId });
}

export function erreurReseau(cause: unknown): ApiError {
  const e = new ApiError({
    status: 0,
    code: "RESEAU_INDISPONIBLE",
    message: "Le serveur ALPHA est injoignable. Vérifiez votre connexion puis réessayez.",
  });
  (e as Error).cause = cause;
  return e;
}
