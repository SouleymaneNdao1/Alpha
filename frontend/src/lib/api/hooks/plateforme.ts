"use client";

/**
 * Hooks de la console FYXOP (F9). Contrat réel : `alpha/plateforme/` du backend.
 * Seuls des métadonnées d'établissement et des compteurs transitent : aucun contenu de dossier.
 *
 * Le code TOTP de confirmation (step-up) s'appelle `code_totp` pour le provisionnement (car `code`
 * y est le code de l'établissement) et `code` pour les autres écritures. Il n'est jamais conservé.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { cheminDepuisUrl } from "../pagination";
import type { PageCurseur, Schema } from "../types";
import { paramsFiltres, TAILLE_PAGE_JOURNAL, type EvenementAudit, type FiltresJournal } from "./audit";

export type EtablissementConsole = Schema<"EtablissementConsole">;
export type EtablissementDetail = Schema<"EtablissementDetail">;
export type StatsEtablissement = Schema<"Stats">;
export type AdministrateurInvite = Schema<"AdministrateurInvite">;
export type ReponseProvisionnement = Schema<"ProvisionnementReponse">;
export type ReponseReinitialisation = Schema<"ReinitialisationReponse">;
export type TypeEtablissement = Schema<"TypeEtablissementEnum">;
export type StatutEtablissement = Schema<"StatutEtablissementEnum">;

/** Code d'erreur 403 de `PATCH` quand la suspension manuelle est coupée (décision P6). */
export const SUSPENSION_DESACTIVEE = "SUSPENSION_MANUELLE_DESACTIVEE";

const RACINE = ["plateforme"] as const;
const base = (id: string) => `/plateforme/etablissements/${encodeURIComponent(id)}`;

/** `GET /plateforme/etablissements?q=` : tableau complet (pas de pagination). */
export function useEtablissements(q: string) {
  return useQuery({
    queryKey: [...RACINE, "etablissements", "liste", q],
    queryFn: ({ signal }) => api.get<EtablissementConsole[]>("/plateforme/etablissements", { signal, params: { q: q.trim() || undefined } }),
    placeholderData: (precedent) => precedent,
    retry: false,
  });
}

/** `GET /plateforme/etablissements/{id}`. */
export function useEtablissement(id: string) {
  return useQuery({
    queryKey: [...RACINE, "etablissements", "fiche", id],
    queryFn: ({ signal }) => api.get<EtablissementDetail>(base(id), { signal }),
    retry: false,
  });
}

export interface IdentiteAdmin {
  email: string;
  prenom: string;
  nom: string;
}

export interface NouvelEtablissement {
  code: string;
  raison_sociale: string;
  type: TypeEtablissement;
  pays: string;
  administrateur: IdentiteAdmin;
  code_totp: string;
}

/** `POST /plateforme/etablissements` → 201 · 409 CODE_EXISTE | EMAIL_EXISTE · 400 VALIDATION · 401 CODE_INVALIDE. */
export function useProvisionner() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: NouvelEtablissement) => api.post<ReponseProvisionnement>("/plateforme/etablissements", v),
    onSuccess: () => void client.invalidateQueries({ queryKey: [...RACINE, "etablissements"] }),
  });
}

/** Mutations de la fiche ; chacune exige le code TOTP (`code`). */
export function useActionsEtablissement(id: string) {
  const client = useQueryClient();
  const modifier = useMutation({
    /** `PATCH` → fiche à jour · 403 SUSPENSION_MANUELLE_DESACTIVEE · 409 ETABLISSEMENT_ARCHIVE. */
    mutationFn: (v: { raison_sociale?: string; statut?: StatutEtablissement; motif?: string; code: string }) => api.patch<EtablissementDetail>(base(id), v),
    onSuccess: (fiche) => {
      client.setQueryData([...RACINE, "etablissements", "fiche", id], fiche);
      void client.invalidateQueries({ queryKey: [...RACINE, "etablissements", "liste"] });
      void client.invalidateQueries({ queryKey: [...RACINE, "audit"] });
    },
  });
  const inviter = useMutation({
    /** `POST …/administrateurs` → 201 · 409 EMAIL_EXISTE. */
    mutationFn: (v: IdentiteAdmin & { code: string }) => api.post<AdministrateurInvite>(`${base(id)}/administrateurs`, v),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [...RACINE, "etablissements"] });
      void client.invalidateQueries({ queryKey: [...RACINE, "audit"] });
    },
  });
  const reinitialiser = useMutation({
    /** `POST …/reinitialisation-authenticator` (P4) → 200 · 409 AUTRE_ADMINISTRATEUR_DISPONIBLE | PAS_ADMINISTRATEUR. */
    mutationFn: (v: { email: string; reference_demande: string; commentaire?: string; code: string }) =>
      api.post<ReponseReinitialisation>(`${base(id)}/reinitialisation-authenticator`, v),
    onSuccess: () => void client.invalidateQueries({ queryKey: [...RACINE, "audit"] }),
  });
  return { modifier, inviter, reinitialiser };
}

/** `GET /plateforme/audit` : mêmes filtres et même curseur que `/audit/evenements` (`next` absolu suivi tel quel). */
export function useAuditPlateforme(filtres: FiltresJournal) {
  return useInfiniteQuery({
    queryKey: [...RACINE, "audit", filtres],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) =>
      pageParam
        ? api.get<PageCurseur<EvenementAudit>>(cheminDepuisUrl(pageParam), { signal })
        : api.get<PageCurseur<EvenementAudit>>("/plateforme/audit", { signal, params: { ...paramsFiltres(filtres), taille: TAILLE_PAGE_JOURNAL } }),
    getNextPageParam: (derniere) => derniere.next ?? undefined,
    retry: false,
  });
}
