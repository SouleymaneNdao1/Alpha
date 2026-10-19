"use client";

/**
 * Hooks d'authentification (F3, F4). Tous les appels à `/auth/*` passent ici :
 * un écart avec le contrat du backend se corrige dans ce seul fichier.
 *
 * Sources du contrat :
 * - connexion, MFA, session, déconnexion : contrat livré par B5 (prioritaire
 *   sur le document) ;
 * - activation, réenrôlement, mot de passe oublié, réinitialisation, téléphone
 *   perdu : architecture § 4.3 à 4.7 et § 5.2 (B6 pas encore livré).
 *
 * Aucun secret (mot de passe, code, secret TOTP, codes de secours) n'est
 * journalisé ni conservé dans le cache de TanStack Query.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";

// ---------------------------------------------------------------------------
// Chemins (base /api/v1 ajoutée par le client ; pas de « / » final côté B5)
// ---------------------------------------------------------------------------

const seg = (jeton: string) => encodeURIComponent(jeton);

export const CHEMINS_AUTH = {
  session: "/auth/session",
  connexion: "/auth/connexion",
  mfa: "/auth/mfa",
  deconnexion: "/auth/deconnexion",
  oubli: "/auth/mot-de-passe/oubli",
  reinitialisation: (j: string) => `/auth/mot-de-passe/reinitialisation/${seg(j)}`,
  telephonePerdu: "/auth/telephone-perdu",
  /** Préfixe commun aux parcours d'activation et de réenrôlement. */
  enrolement: (parcours: Parcours, j: string) => `/auth/${parcours}/${seg(j)}`,
} as const;

// ---------------------------------------------------------------------------
// Types du contrat
// ---------------------------------------------------------------------------

export interface Moi {
  id: string;
  prenom: string;
  nom: string;
  initiales: string;
  email: string;
  telephone_mobile: string | null;
  langue: string;
  etablissement: { id: string; raison_sociale: string; type: string; statut: string } | null;
  role_principal: { id: string; libelle: string; unite: string | null } | null;
  affectations: Array<{ role: { id: string; libelle: string }; unite: { id: string; libelle: string } | null; principal: boolean }>;
  permissions: string[];
  /** COMPTE, ADMINISTRATION, AUDIT ; ["CONSOLE"] pour un super-admin. */
  modules: string[];
  signature_bloquee: boolean;
  inactivite_session_min: number;
  est_super_admin: boolean;
  mot_de_passe_expire: boolean;
}

export type MethodeMfa = "TOTP" | "CODE_SECOURS";

export interface ReponseConnexion {
  etape: "MFA_REQUIS" | "REENROLEMENT_REQUIS";
  methodes: MethodeMfa[];
}

export interface ReponseMfa {
  utilisateur: Moi;
  codes_secours_restants: number;
}

export type PreuveMfa = { code: string } | { code_secours: string };

/** `activation` (invitation, § 4.3) ou `reenrolement` (après téléphone perdu, § 4.5). */
export type Parcours = "activation" | "reenrolement";

/** Réponse normalisée de `GET /auth/{parcours}/{jeton}`. */
export interface Invitation {
  prenom: string;
  etablissement: string;
  /** Absent pour le réenrôlement. */
  role: string | null;
  /** Étape enregistrée côté serveur (`MDP_OK` après le mot de passe). */
  etape: string | null;
}

export interface Authenticator {
  /** QR code SVG généré par le backend (segno). */
  qr_svg: string;
  /** Secret en groupes de 4 (« JBSW Y3DP … »), pour une saisie manuelle. */
  secret_affichable: string;
  emetteur: string;
  compte: string;
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export const CLE_SESSION = ["auth", "session"] as const;

/** `GET /auth/session` : 200 Moi, 401 NON_AUTHENTIFIE ou SESSION_EXPIREE. */
export function useSession(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: CLE_SESSION,
    queryFn: ({ signal }) => api.get<Moi>(CHEMINS_AUTH.session, { signal, fond: true, redirigerSiSessionExpiree: false }),
    enabled: options.active ?? true,
    retry: false,
  });
}

/** `POST /auth/deconnexion` → 204. Vide le cache (données de l'utilisateur). */
export function useDeconnexion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>(CHEMINS_AUTH.deconnexion, undefined, { redirigerSiSessionExpiree: false }),
    onSettled: () => client.clear(),
  });
}

// ---------------------------------------------------------------------------
// Connexion + MFA (contrat B5)
// ---------------------------------------------------------------------------

/** `POST /auth/connexion {email, mot_de_passe}` → `{etape, methodes}`. */
export function useConnexion() {
  return useMutation({
    mutationFn: (v: { email: string; mot_de_passe: string }) =>
      api.post<ReponseConnexion>(CHEMINS_AUTH.connexion, v, { redirigerSiSessionExpiree: false }),
  });
}

/**
 * `POST /auth/mfa {code}` ou `{code_secours}` → `{utilisateur, codes_secours_restants}`.
 * Le backend renouvelle la session et le jeton CSRF : le client relit le cookie
 * `alpha_csrf` à chaque requête, rien à faire ici.
 */
export function useMfa() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (preuve: PreuveMfa) => api.post<ReponseMfa>(CHEMINS_AUTH.mfa, preuve, { redirigerSiSessionExpiree: false }),
    onSuccess: (r) => client.setQueryData(CLE_SESSION, r.utilisateur),
  });
}

// ---------------------------------------------------------------------------
// Activation et réenrôlement (§ 4.3, 4.5 — contrat du document, B6)
// ---------------------------------------------------------------------------

function texte(v: unknown): string | null {
  if (typeof v === "string") return v;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    for (const cle of ["raison_sociale", "libelle", "nom"]) if (typeof o[cle] === "string") return o[cle] as string;
  }
  return null;
}

/** Accepte `etablissement`/`role` en chaîne ou en objet (`{raison_sociale}`, `{libelle}`). */
function normaliserInvitation(brut: Record<string, unknown>): Invitation {
  return {
    prenom: texte(brut.prenom) ?? "",
    etablissement: texte(brut.etablissement) ?? "",
    role: texte(brut.role),
    etape: texte(brut.etape),
  };
}

/** `GET /auth/{parcours}/{jeton}` → 200 `{prenom, etablissement, role?, etape?}` · 410 JETON_INVALIDE. */
export function useInvitation(parcours: Parcours, jeton: string | null) {
  return useQuery({
    queryKey: ["auth", parcours, jeton],
    queryFn: async ({ signal }) =>
      normaliserInvitation(
        await api.get<Record<string, unknown>>(CHEMINS_AUTH.enrolement(parcours, jeton!), { signal, redirigerSiSessionExpiree: false }),
      ),
    enabled: !!jeton,
    retry: false,
    staleTime: Infinity,
  });
}

/**
 * Étape « Mot de passe ».
 * - activation : `{mot_de_passe, confirmation}` (définition) → 204 · 400 VALIDATION ;
 * - réenrôlement : `{mot_de_passe}` (vérification du mot de passe actuel) → 204 · 401.
 */
export function useEtapeMotDePasse(parcours: Parcours, jeton: string) {
  return useMutation({
    mutationFn: (v: { mot_de_passe: string; confirmation?: string }) =>
      api.post<void>(
        `${CHEMINS_AUTH.enrolement(parcours, jeton)}/mot-de-passe`,
        parcours === "activation" ? { mot_de_passe: v.mot_de_passe, confirmation: v.confirmation } : { mot_de_passe: v.mot_de_passe },
        { redirigerSiSessionExpiree: false },
      ),
  });
}

/** Étape « Téléphone » : `POST …/authenticator` → `{qr_svg, secret_affichable, emetteur, compte}` · 409 ETAPE_INVALIDE. */
export function useGenererAuthenticator(parcours: Parcours, jeton: string) {
  return useMutation({
    mutationFn: () =>
      api.post<Authenticator>(`${CHEMINS_AUTH.enrolement(parcours, jeton)}/authenticator`, undefined, { redirigerSiSessionExpiree: false }),
  });
}

/** Étape « Vérification » : `POST …/authenticator/confirmer {code}` → `{codes_secours: [10]}` · 401 CODE_INVALIDE. */
export function useConfirmerAuthenticator(parcours: Parcours, jeton: string) {
  return useMutation({
    mutationFn: (code: string) =>
      api.post<{ codes_secours: string[] }>(`${CHEMINS_AUTH.enrolement(parcours, jeton)}/authenticator/confirmer`, { code }, {
        redirigerSiSessionExpiree: false,
      }),
  });
}

/** Fin : `POST …/terminer {codes_conserves: true}` → 200 Moi (session ouverte). */
export function useTerminerEnrolement(parcours: Parcours, jeton: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<Moi>(`${CHEMINS_AUTH.enrolement(parcours, jeton)}/terminer`, { codes_conserves: true }, { redirigerSiSessionExpiree: false }),
    onSuccess: (moi) => {
      if (moi && typeof moi === "object" && "id" in moi) client.setQueryData(CLE_SESSION, moi);
    },
  });
}

// ---------------------------------------------------------------------------
// Mot de passe oublié, réinitialisation, téléphone perdu (§ 4.5, 4.7)
// ---------------------------------------------------------------------------

/** `POST /auth/mot-de-passe/oubli {email}` → 202 (toujours). */
export function useOubliMotDePasse() {
  return useMutation({
    mutationFn: (v: { email: string }) => api.post<void>(CHEMINS_AUTH.oubli, v, { redirigerSiSessionExpiree: false }),
  });
}

/** `GET /auth/mot-de-passe/reinitialisation/{jeton}` → `{email_masque}` · 410. */
export function useLienReinitialisation(jeton: string) {
  return useQuery({
    queryKey: ["auth", "reinitialisation", jeton],
    queryFn: ({ signal }) =>
      api.get<{ email_masque: string }>(CHEMINS_AUTH.reinitialisation(jeton), { signal, redirigerSiSessionExpiree: false }),
    retry: false,
    staleTime: Infinity,
  });
}

/** `POST /auth/mot-de-passe/reinitialisation/{jeton} {mot_de_passe, confirmation, code | code_secours}` → 204 · 400 · 401 CODE_INVALIDE · 410. */
export function useReinitialiserMotDePasse(jeton: string) {
  return useMutation({
    mutationFn: (v: { mot_de_passe: string; confirmation: string } & PreuveMfa) =>
      api.post<void>(CHEMINS_AUTH.reinitialisation(jeton), v, { redirigerSiSessionExpiree: false }),
  });
}

/** `POST /auth/telephone-perdu {email, mot_de_passe}` → 202 (toujours). */
export function useSignalerTelephonePerdu() {
  return useMutation({
    mutationFn: (v: { email: string; mot_de_passe: string }) =>
      api.post<void>(CHEMINS_AUTH.telephonePerdu, v, { redirigerSiSessionExpiree: false }),
  });
}
