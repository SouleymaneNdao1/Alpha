"use client";

/**
 * Hooks de « Mon compte » (F6). Contrat réel : serializers du backend
 * (`alpha/comptes/serializers_moi.py`, `alpha/delegations/serializers.py`,
 * `alpha/notifications/serializers.py`). Les routes de `alpha.delegations`
 * se terminent par « / » ; celles de `/moi/*` (comptes, notifications) non.
 *
 * Aucun mot de passe, code TOTP ni code de secours n'est conservé dans le cache.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import type { Page, Schema } from "../types";
import { CLE_SESSION, type Authenticator, type Moi } from "./auth";

export type Securite = Schema<"Securite">;
export type SessionMoi = Schema<"SessionMoi">;
export type Absence = Schema<"Absence">;
export type AbsenceDetail = Schema<"AbsenceDetail">;
export type DelegatairePossible = Schema<"DelegatairePossible">;
export type DelegationRecue = Schema<"DelegationRecue">;
export type PreferencesNotification = Schema<"PreferencesNotification">;

export type MotifAbsence = "CONGE" | "MISSION" | "FORMATION" | "MALADIE" | "AUTRE";
export type StatutAbsence = "SOUMISE" | "VALIDEE" | "REFUSEE" | "ANNULEE";

// ---------------------------------------------------------------------------
// Profil, sécurité
// ---------------------------------------------------------------------------

/** `PATCH /moi {prenom, nom, telephone_mobile, langue}` → `Moi` (met à jour la session en cache). */
export function useModifierProfil() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { prenom?: string; nom?: string; telephone_mobile?: string | null; langue?: string }) => api.patch<Moi>("/moi", v),
    onSuccess: (moi) => client.setQueryData(CLE_SESSION, moi),
  });
}

export const CLE_SECURITE = ["moi", "securite"] as const;

/** `GET /moi/securite`. */
export function useSecurite() {
  return useQuery({ queryKey: CLE_SECURITE, queryFn: ({ signal }) => api.get<Securite>("/moi/securite", { signal }) });
}

/** `POST /moi/mot-de-passe {actuel, nouveau, confirmation, code}` → 204. 401 MOT_DE_PASSE_INCORRECT | CODE_INVALIDE · 423 COMPTE_VERROUILLE. */
export function useChangerMotDePasse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { actuel: string; nouveau: string; confirmation: string; code: string }) => api.post<void>("/moi/mot-de-passe", v),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: CLE_SECURITE });
      void client.invalidateQueries({ queryKey: CLE_SESSIONS });
      void client.invalidateQueries({ queryKey: CLE_SESSION });
    },
  });
}

/** Changement d'Authenticator, étape 1 : `POST /moi/authenticator/changement {code_actuel}` → QR de la nouvelle application. */
export function useDemanderChangementAuthenticator() {
  return useMutation({ mutationFn: (code_actuel: string) => api.post<Authenticator>("/moi/authenticator/changement", { code_actuel }) });
}

/** Étape 2 : `POST /moi/authenticator/changement/confirmer {code_nouveau}` → 204. */
export function useConfirmerChangementAuthenticator() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (code_nouveau: string) => api.post<void>("/moi/authenticator/changement/confirmer", { code_nouveau }),
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_SECURITE }),
  });
}

/** `POST /moi/codes-secours {code}` → `{codes_secours: [10]}`, affichés une seule fois (jamais mis en cache). */
export function useRegenererCodesSecours() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.post<{ codes_secours: string[] }>("/moi/codes-secours", { code }),
    gcTime: 0,
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_SECURITE }),
  });
}

/** `POST /moi/telephone-perdu` → 202 `{message}` ; toutes les sessions sont révoquées, y compris celle-ci. */
export function useSignalerTelephonePerdu() {
  return useMutation({
    mutationFn: () => api.post<{ message: string }>("/moi/telephone-perdu", undefined, { redirigerSiSessionExpiree: false }),
  });
}

export const CLE_SESSIONS = ["moi", "sessions"] as const;

/** `GET /moi/sessions` (tableau, non paginé). */
export function useMesSessions() {
  return useQuery({ queryKey: CLE_SESSIONS, queryFn: ({ signal }) => api.get<SessionMoi[]>("/moi/sessions", { signal }) });
}

/** `DELETE /moi/sessions/{id}` → 204 · 409 SESSION_COURANTE. */
export function useRevoquerSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/moi/sessions/${encodeURIComponent(id)}`),
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_SESSIONS }),
  });
}

/** `POST /moi/sessions/revoquer-autres` → `{revoquees}`. */
export function useRevoquerAutresSessions() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ revoquees: number }>("/moi/sessions/revoquer-autres"),
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_SESSIONS }),
  });
}

// ---------------------------------------------------------------------------
// Absences et délégations (routes avec « / » final)
// ---------------------------------------------------------------------------

export const CLE_ABSENCES = ["moi", "absences"] as const;

/** `GET /moi/absences` (page ; on lit les 100 plus récentes). */
export function useMesAbsences() {
  return useQuery({
    queryKey: CLE_ABSENCES,
    queryFn: ({ signal }) => api.get<Page<Absence>>("/moi/absences", { signal, params: { taille: 100 } }),
  });
}

export interface CreationAbsence {
  debut: string;
  fin: string;
  motif: MotifAbsence;
  commentaire: string;
  delegataire_id: string;
  role_id?: string | null;
}

/** `POST /moi/absences` → 201. 409 CHEVAUCHEMENT | POUVOIRS_INSUFFISANTS | SOUS_DELEGATION_INTERDITE | AUCUN_VALIDEUR. */
export function useCreerAbsence() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: CreationAbsence) => api.post<AbsenceDetail>("/moi/absences", v),
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_ABSENCES }),
  });
}

/** `POST /moi/absences/{id}/annuler` → 200 · 409 STATUT_INVALIDE. */
export function useAnnulerAbsence() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AbsenceDetail>(`/moi/absences/${encodeURIComponent(id)}/annuler`),
    onSuccess: () => void client.invalidateQueries({ queryKey: CLE_ABSENCES }),
  });
}

/** `GET /moi/delegataires-possibles?q=` (tableau). */
export function useDelegataires(q: string) {
  return useQuery({
    queryKey: ["moi", "delegataires-possibles", q],
    queryFn: ({ signal }) => api.get<DelegatairePossible[]>("/moi/delegataires-possibles", { signal, params: { q: q || undefined } }),
    staleTime: 30_000,
  });
}

/** `GET /moi/delegations-recues` (tableau). */
export function useDelegationsRecues() {
  return useQuery({ queryKey: ["moi", "delegations-recues"], queryFn: ({ signal }) => api.get<DelegationRecue[]>("/moi/delegations-recues", { signal }) });
}

/** `GET /absences/{id}` (demandeur, valideur, admin.absences ou délégataire du valideur ; sinon 404). */
export function useAbsence(id: string) {
  return useQuery({
    queryKey: ["absences", id],
    queryFn: ({ signal }) => api.get<AbsenceDetail>(`/absences/${encodeURIComponent(id)}`, { signal }),
    retry: false,
  });
}

function invalider(client: ReturnType<typeof useQueryClient>, id: string, absence: AbsenceDetail) {
  client.setQueryData(["absences", id], absence);
  void client.invalidateQueries({ queryKey: ["taches"] });
  void client.invalidateQueries({ queryKey: CLE_ABSENCES });
}

/** `POST /absences/{id}/valider` → 200 · 403 · 409 STATUT_INVALIDE | ABSENCE_EXPIREE | POUVOIRS_INSUFFISANTS | SOUS_DELEGATION_INTERDITE. */
export function useValiderAbsence(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<AbsenceDetail>(`/absences/${encodeURIComponent(id)}/valider`),
    onSuccess: (a) => invalider(client, id, a),
  });
}

/** `POST /absences/{id}/refuser {motif}` → 200 · 400 VALIDATION · 409 STATUT_INVALIDE. */
export function useRefuserAbsence(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (motif: string) => api.post<AbsenceDetail>(`/absences/${encodeURIComponent(id)}/refuser`, { motif }),
    onSuccess: (a) => invalider(client, id, a),
  });
}

// ---------------------------------------------------------------------------
// Préférences de notification
// ---------------------------------------------------------------------------

export const CLE_PREFERENCES = ["moi", "preferences-notification"] as const;

/** `GET /moi/preferences-notification`. */
export function usePreferencesNotification() {
  return useQuery({ queryKey: CLE_PREFERENCES, queryFn: ({ signal }) => api.get<PreferencesNotification>("/moi/preferences-notification", { signal }) });
}

/** `PUT /moi/preferences-notification` (tous les champs, `heure_resume` « HH:MM »). */
export function useEnregistrerPreferences() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: PreferencesNotification) => api.put<PreferencesNotification>("/moi/preferences-notification", v),
    onSuccess: (p) => client.setQueryData(CLE_PREFERENCES, p),
  });
}
