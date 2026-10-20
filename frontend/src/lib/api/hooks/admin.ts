"use client";

/**
 * Hooks de l'administration (F7). Contrat réel : `alpha/comptes/vues_admin.py`,
 * `vues_signalements.py`, `alpha/organisation/vues.py`, `alpha/tenancy/parametres.py`.
 * Routes sans « / » final. Les listes d'utilisateurs et de signalements sont
 * paginées ; les rôles, permissions et l'arbre des unités sont des tableaux.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { cheminDepuisUrl } from "../pagination";
import type { Page, Schema } from "../types";

export type UtilisateurListe = Schema<"UtilisateurListe">;
export type UtilisateurDetail = Schema<"UtilisateurDetail">;
export type Affectation = Schema<"Affectation">;
export type RoleCatalogue = Schema<"Role">;
export type PermissionSysteme = Schema<"Permission">;
export type UniteArbre = Schema<"UniteArbre">;
export type ParametresSecurite = Schema<"ParametresSecurite">;
export type SignalementTelephone = Schema<"SignalementTelephone">;
export type EvenementHistorique = Schema<"EvenementAudit">;
export type TypeUnite = "DIRECTION" | "SERVICE" | "AGENCE" | "COMITE";
export type ModeVerification = "PRESENTIEL_PIECE" | "RAPPEL_TELEPHONIQUE" | "VISIO" | "AUTRE";
export type StatutUtilisateur = "INVITE" | "ACTIF" | "SUSPENDU" | "DESACTIVE";

const RACINE_UTILISATEURS = ["admin", "utilisateurs"] as const;

// ---------------------------------------------------------------------------
// Utilisateurs
// ---------------------------------------------------------------------------

export interface FiltresUtilisateurs {
  q: string;
  roleId: string;
}

/** `GET /admin/utilisateurs?q=&role_id=&taille=` (pagination par numéro de page, suivie par `next`). */
export function useUtilisateurs(filtres: FiltresUtilisateurs, taille = 25) {
  return useInfiniteQuery({
    queryKey: [...RACINE_UTILISATEURS, "liste", filtres.q, filtres.roleId, taille],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      pageParam
        ? api.get<Page<UtilisateurListe>>(cheminDepuisUrl(pageParam), { signal })
        : api.get<Page<UtilisateurListe>>("/admin/utilisateurs", { signal, params: { q: filtres.q || undefined, role_id: filtres.roleId || undefined, taille } }),
    getNextPageParam: (derniere) => derniere.next,
    retry: false,
  });
}

/** `GET /admin/utilisateurs/historique?limite=3`. */
export function useHistoriqueUtilisateurs(limite = 3) {
  return useQuery({
    queryKey: [...RACINE_UTILISATEURS, "historique", limite],
    queryFn: ({ signal }) => api.get<EvenementHistorique[]>("/admin/utilisateurs/historique", { signal, params: { limite } }),
    retry: false,
  });
}

export interface InvitationUtilisateur {
  email: string;
  prenom: string;
  nom: string;
  role_id: string;
  unite_id?: string | null;
  responsable_id?: string | null;
  telephone_mobile?: string | null;
}

/** `POST /admin/utilisateurs` → 201 fiche · 409 EMAIL_EXISTE · 400 VALIDATION | ROLE_HORS_CATALOGUE. */
export function useInviterUtilisateur() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: InvitationUtilisateur) => api.post<UtilisateurDetail>("/admin/utilisateurs", v),
    onSuccess: () => void client.invalidateQueries({ queryKey: RACINE_UTILISATEURS }),
  });
}

/** `GET /admin/utilisateurs/{id}`. */
export function useUtilisateur(id: string) {
  return useQuery({
    queryKey: [...RACINE_UTILISATEURS, "fiche", id],
    queryFn: ({ signal }) => api.get<UtilisateurDetail>(`/admin/utilisateurs/${encodeURIComponent(id)}`, { signal }),
    retry: false,
  });
}

/** Mutations de la fiche : elles renvoient toutes la fiche à jour, placée directement en cache. */
export function useActionsUtilisateur(id: string) {
  const client = useQueryClient();
  const base = `/admin/utilisateurs/${encodeURIComponent(id)}`;
  const cle = [...RACINE_UTILISATEURS, "fiche", id];
  const apres = (fiche: UtilisateurDetail) => {
    client.setQueryData(cle, fiche);
    void client.invalidateQueries({ queryKey: [...RACINE_UTILISATEURS, "liste"] });
    void client.invalidateQueries({ queryKey: [...RACINE_UTILISATEURS, "historique"] });
  };
  const rafraichir = () => {
    void client.invalidateQueries({ queryKey: [...RACINE_UTILISATEURS] });
    void client.invalidateQueries({ queryKey: ["admin", "roles"] });
  };
  return {
    modifier: useMutation({
      mutationFn: (v: { prenom?: string; nom?: string; telephone_mobile?: string | null; responsable_id?: string | null }) =>
        api.patch<UtilisateurDetail>(base, v),
      onSuccess: apres,
    }),
    suspendre: useMutation({
      mutationFn: (motif: string) => api.post<UtilisateurDetail & { sessions_revoquees: number }>(`${base}/suspendre`, { motif }),
      onSuccess: apres,
    }),
    reactiver: useMutation({ mutationFn: () => api.post<UtilisateurDetail>(`${base}/reactiver`), onSuccess: apres }),
    deverrouiller: useMutation({ mutationFn: () => api.post<UtilisateurDetail>(`${base}/deverrouiller`), onSuccess: apres }),
    renvoyerInvitation: useMutation({ mutationFn: () => api.post<{ expire_le: string }>(`${base}/renvoyer-invitation`) }),
    revoquerSessions: useMutation({
      mutationFn: () => api.post<{ revoquees: number }>(`${base}/sessions/revoquer`),
      onSuccess: rafraichir,
    }),
    affecter: useMutation({
      mutationFn: (v: { role_id: string; unite_id?: string | null; principal: boolean }) => api.post<Affectation>(`${base}/affectations`, v),
      onSuccess: rafraichir,
    }),
    terminerAffectation: useMutation({
      mutationFn: (affectationId: string) => api.post<Affectation>(`/admin/affectations/${encodeURIComponent(affectationId)}/terminer`),
      onSuccess: rafraichir,
    }),
  };
}

// ---------------------------------------------------------------------------
// Rôles et permissions
// ---------------------------------------------------------------------------

const RACINE_ROLES = ["admin", "roles"] as const;

/** `GET /admin/roles` (tableau, tri par ordre puis libellé). Lecture : `admin.roles` ou `admin.utilisateurs`. */
export function useRoles(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: RACINE_ROLES,
    queryFn: ({ signal }) => api.get<RoleCatalogue[]>("/admin/roles", { signal }),
    enabled: options.active ?? true,
    retry: false,
  });
}

/** `GET /admin/permissions` (`admin.roles`). */
export function usePermissions() {
  return useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: ({ signal }) => api.get<PermissionSysteme[]>("/admin/permissions", { signal }),
    staleTime: Infinity,
    retry: false,
  });
}

export interface ChampsRole {
  libelle: string;
  description?: string;
  permissions?: string[];
  ordre?: number;
}

export function useActionsRoles() {
  const client = useQueryClient();
  const rafraichir = () => void client.invalidateQueries({ queryKey: RACINE_ROLES });
  return {
    creer: useMutation({ mutationFn: (v: ChampsRole & { code?: string }) => api.post<RoleCatalogue>("/admin/roles", v), onSuccess: rafraichir }),
    modifier: useMutation({
      mutationFn: ({ id, ...v }: ChampsRole & { id: string }) => api.patch<RoleCatalogue>(`/admin/roles/${encodeURIComponent(id)}`, v),
      onSuccess: rafraichir,
    }),
    desactiver: useMutation({ mutationFn: (id: string) => api.post<RoleCatalogue>(`/admin/roles/${encodeURIComponent(id)}/desactiver`), onSuccess: rafraichir }),
    activer: useMutation({ mutationFn: (id: string) => api.post<RoleCatalogue>(`/admin/roles/${encodeURIComponent(id)}/activer`), onSuccess: rafraichir }),
  };
}

// ---------------------------------------------------------------------------
// Unités
// ---------------------------------------------------------------------------

const RACINE_UNITES = ["admin", "unites"] as const;

/** `GET /admin/unites` → arbre (`enfants` imbriqués). */
export function useUnites(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: RACINE_UNITES,
    queryFn: ({ signal }) => api.get<UniteArbre[]>("/admin/unites", { signal }),
    enabled: options.active ?? true,
    retry: false,
  });
}

export interface ChampsUnite {
  parent_id?: string | null;
  type: TypeUnite;
  code: string;
  libelle: string;
  actif?: boolean;
}

export function useActionsUnites() {
  const client = useQueryClient();
  const rafraichir = () => void client.invalidateQueries({ queryKey: RACINE_UNITES });
  return {
    creer: useMutation({ mutationFn: (v: ChampsUnite) => api.post<Omit<UniteArbre, "enfants">>("/admin/unites", v), onSuccess: rafraichir }),
    modifier: useMutation({
      mutationFn: ({ id, ...v }: Partial<ChampsUnite> & { id: string }) => api.patch<Omit<UniteArbre, "enfants">>(`/admin/unites/${encodeURIComponent(id)}`, v),
      onSuccess: rafraichir,
    }),
  };
}

/** Aplatit l'arbre en liste ordonnée avec la profondeur (indentation des listes déroulantes). */
export function aplatirUnites(arbre: UniteArbre[], profondeur = 0): Array<UniteArbre & { profondeur: number }> {
  return arbre.flatMap((u) => [{ ...u, profondeur }, ...aplatirUnites(u.enfants, profondeur + 1)]);
}

// ---------------------------------------------------------------------------
// Paramètres de sécurité et signalements « téléphone perdu »
// ---------------------------------------------------------------------------

const CLE_PARAMETRES = ["admin", "parametres-securite"] as const;

/** `GET /admin/parametres-securite` (`admin.securite`). */
export function useParametresSecurite() {
  return useQuery({ queryKey: CLE_PARAMETRES, queryFn: ({ signal }) => api.get<ParametresSecurite>("/admin/parametres-securite", { signal }), retry: false });
}

export type ModificationParametres = Partial<Omit<ParametresSecurite, "modules_actifs" | "modifie_le">> & { code: string };

/** `PATCH /admin/parametres-securite` avec `code` TOTP · 401 CODE_INVALIDE · 400 VALIDATION (bornes). */
export function useModifierParametresSecurite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: ModificationParametres) => api.patch<ParametresSecurite>("/admin/parametres-securite", v),
    gcTime: 0,
    onSuccess: (p) => client.setQueryData(CLE_PARAMETRES, p),
  });
}

const RACINE_SIGNALEMENTS = ["admin", "signalements-telephone"] as const;

/** `GET /admin/signalements-telephone?statut=&taille=` (page). */
export function useSignalements(statut: "OUVERT" | "" = "") {
  return useQuery({
    queryKey: [...RACINE_SIGNALEMENTS, statut],
    queryFn: ({ signal }) => api.get<Page<SignalementTelephone>>("/admin/signalements-telephone", { signal, params: { statut: statut || undefined, taille: 50 } }),
    retry: false,
  });
}

/** Traitement : `reinitialiser` {mode_verification, commentaire, code} ou `annuler` {commentaire, code}. 403 AUTO_TRAITEMENT_INTERDIT · 409 SIGNALEMENT_DEJA_TRAITE · 401 CODE_INVALIDE. */
export function useTraiterSignalement() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, ...corps }: { id: string; action: "reinitialiser" | "annuler"; code: string; commentaire: string; mode_verification?: ModeVerification }) =>
      api.post<SignalementTelephone>(`/admin/signalements-telephone/${encodeURIComponent(id)}/${action}`, corps),
    gcTime: 0,
    onSuccess: () => void client.invalidateQueries({ queryKey: RACINE_SIGNALEMENTS }),
  });
}

// ---------------------------------------------------------------------------
// Absences et délégations de l'établissement (B13)
// ---------------------------------------------------------------------------

export type AbsenceAdmin = Schema<"AbsenceAdmin">;
export type DelegationAdmin = Schema<"DelegationAdmin">;
export type Candidat = Schema<"Candidat">;
export type StatutDelegation = "EN_ATTENTE" | "ACTIVE" | "TERMINEE" | "ANNULEE" | "REFUSEE";

const RACINE_ABSENCES = ["admin", "absences"] as const;
const RACINE_DELEGATIONS = ["admin", "delegations"] as const;

export interface FiltresPeriode {
  statut: string;
  du: string;
  au: string;
}

function parametresPeriode(f: FiltresPeriode, taille: number) {
  return { statut: f.statut || undefined, du: f.du || undefined, au: f.au || undefined, taille };
}

/** `GET /admin/absences?statut=&du=&au=&taille=` (`admin.absences`, page). */
export function useAbsencesAdmin(filtres: FiltresPeriode, options: { active?: boolean } = {}, taille = 25) {
  return useInfiniteQuery({
    queryKey: [...RACINE_ABSENCES, "liste", filtres.statut, filtres.du, filtres.au, taille],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      pageParam
        ? api.get<Page<AbsenceAdmin>>(cheminDepuisUrl(pageParam), { signal })
        : api.get<Page<AbsenceAdmin>>("/admin/absences", { signal, params: parametresPeriode(filtres, taille) }),
    getNextPageParam: (derniere) => derniere.next,
    enabled: options.active ?? true,
    retry: false,
  });
}

/** `GET /admin/delegations?statut=&du=&au=&taille=` (`admin.absences` ou `admin.utilisateurs`, page). */
export function useDelegationsAdmin(filtres: FiltresPeriode, taille = 25) {
  return useInfiniteQuery({
    queryKey: [...RACINE_DELEGATIONS, "liste", filtres.statut, filtres.du, filtres.au, taille],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      pageParam
        ? api.get<Page<DelegationAdmin>>(cheminDepuisUrl(pageParam), { signal })
        : api.get<Page<DelegationAdmin>>("/admin/delegations", { signal, params: parametresPeriode(filtres, taille) }),
    getNextPageParam: (derniere) => derniere.next,
    retry: false,
  });
}

/** `GET /admin/absences/candidats?q=&pour=` : sans `pour`, tous les actifs ; avec, contrôle P5 (`pouvoirs_suffisants`). */
export function useCandidatsAdmin(q: string, pour: string | null) {
  return useQuery({
    queryKey: [...RACINE_ABSENCES, "candidats", q, pour],
    queryFn: ({ signal }) => api.get<Candidat[]>("/admin/absences/candidats", { signal, params: { q: q || undefined, pour: pour || undefined } }),
    staleTime: 30_000,
    retry: false,
  });
}

export interface CreationAbsenceAdmin {
  utilisateur_id: string;
  debut: string;
  fin: string;
  motif: "CONGE" | "MISSION" | "FORMATION" | "MALADIE" | "AUTRE";
  commentaire: string;
  delegataire_id: string;
  valider: boolean;
}

/**
 * Écritures : `POST /admin/absences` (201 · 409 CHEVAUCHEMENT | POUVOIRS_INSUFFISANTS | SOUS_DELEGATION_INTERDITE | AUCUN_VALIDEUR),
 * décision via `POST /absences/{id}/valider|refuser` (routes de validation, ouvertes à `admin.absences`),
 * `POST /admin/delegations/{id}/revoquer {motif}` (200 · 409 STATUT_INVALIDE).
 */
export function useActionsAbsencesAdmin() {
  const client = useQueryClient();
  const rafraichir = () => {
    void client.invalidateQueries({ queryKey: RACINE_ABSENCES });
    void client.invalidateQueries({ queryKey: RACINE_DELEGATIONS });
    void client.invalidateQueries({ queryKey: ["taches"] });
  };
  return {
    creer: useMutation({ mutationFn: (v: CreationAbsenceAdmin) => api.post<AbsenceAdmin>("/admin/absences", v), onSuccess: rafraichir }),
    valider: useMutation({ mutationFn: (id: string) => api.post<AbsenceAdmin>(`/absences/${encodeURIComponent(id)}/valider`), onSuccess: rafraichir }),
    refuser: useMutation({
      mutationFn: ({ id, motif }: { id: string; motif: string }) => api.post<AbsenceAdmin>(`/absences/${encodeURIComponent(id)}/refuser`, { motif }),
      onSuccess: rafraichir,
    }),
    revoquer: useMutation({
      mutationFn: ({ id, motif }: { id: string; motif: string }) => api.post<DelegationAdmin>(`/admin/delegations/${encodeURIComponent(id)}/revoquer`, { motif }),
      onSuccess: rafraichir,
    }),
  };
}
