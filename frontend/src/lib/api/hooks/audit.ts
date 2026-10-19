"use client";

/**
 * Hooks du journal d'audit (F8) : `/audit/evenements` (curseur), `/audit/indicateurs`,
 * `/audit/export.xlsx`, `/audit/controles`. Contrat réel : `alpha/audit/` du backend.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Params } from "../client";
import { cheminDepuisUrl } from "../pagination";
import type { Page, PageCurseur } from "../types";

export type Periode = "aujourdhui" | "7j" | "30j";

export interface FiltresJournal {
  q: string;
  categorie: string;
  periode: Periode;
}

export interface EvenementAudit {
  seq: number;
  horodatage: string;
  acteur_type: string;
  acteur_libelle: string;
  categorie: string;
  action: string;
  action_libelle: string;
  objet_type: string;
  objet_id: string;
  objet_libelle: string;
  avant: Record<string, unknown> | null;
  apres: Record<string, unknown> | null;
  detail: string;
  ip: string | null;
  hash: string;
  hash_court: string;
}

export type StatutControle = "EN_COURS" | "INTACTE" | "ROMPUE" | "ERREUR";

export interface DernierControle {
  id: string;
  statut: StatutControle;
  lance_le: string;
  termine_le: string | null;
  dernier_seq: number | null;
  premier_seq_invalide: number | null;
  message: string;
}

export interface IndicateursAudit {
  evenements_aujourdhui: number;
  connexions_echouees_24h: number;
  actions_administration_24h: number;
  dernier_controle: DernierControle | null;
  controle_en_cours: boolean;
}

export interface ControleAudit {
  id: string;
  lance_le: string;
  termine_le: string | null;
  declencheur: "PLANIFIE" | "MANUEL";
  statut: StatutControle;
  nb_evenements: number | null;
  dernier_seq: number | null;
  premier_seq_invalide: number | null;
  message: string;
}

export const TAILLE_PAGE_JOURNAL = 50;

/** Paramètres communs à la liste et à l'export (vides ignorés). */
export function paramsFiltres(f: FiltresJournal): Params {
  return { q: f.q.trim() || null, categorie: f.categorie || null, periode: f.periode };
}

/** Liste par curseur : `next` est une URL absolue, suivie telle quelle (chemin + requête). */
export function useEvenementsAudit(filtres: FiltresJournal) {
  return useInfiniteQuery({
    queryKey: ["audit", "evenements", filtres],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) =>
      pageParam
        ? api.get<PageCurseur<EvenementAudit>>(cheminDepuisUrl(pageParam), { signal })
        : api.get<PageCurseur<EvenementAudit>>("/audit/evenements", {
            signal,
            params: { ...paramsFiltres(filtres), taille: TAILLE_PAGE_JOURNAL },
          }),
    getNextPageParam: (derniere) => derniere.next ?? undefined,
    retry: false,
  });
}

export const CLE_INDICATEURS = ["audit", "indicateurs"] as const;
export const INTERVALLE_SUIVI_CONTROLE_MS = 3_000;

/** Indicateurs ; interrogés toutes les 3 s tant qu'un contrôle est en cours (appel de fond). */
export function useIndicateursAudit() {
  return useQuery({
    queryKey: CLE_INDICATEURS,
    queryFn: ({ signal }) => api.get<IndicateursAudit>("/audit/indicateurs", { signal, fond: true }),
    refetchInterval: (q) => (q.state.data?.controle_en_cours ? INTERVALLE_SUIVI_CONTROLE_MS : false),
    retry: false,
  });
}

/** Cinq derniers contrôles (plus récent d'abord). */
export function useControlesAudit() {
  return useQuery({
    queryKey: ["audit", "controles"],
    queryFn: ({ signal }) => api.get<Page<ControleAudit>>("/audit/controles", { signal, params: { taille: 5 } }),
    retry: false,
  });
}

/** `POST /audit/controles` → 202 `{id, statut}` · 409 CONTROLE_EN_COURS. */
export function useLancerControle() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ id: string; statut: StatutControle }>("/audit/controles"),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: CLE_INDICATEURS });
      void client.invalidateQueries({ queryKey: ["audit", "controles"] });
    },
  });
}

/** `GET /audit/export.xlsx` avec les filtres courants → Blob · 400 EXPORT_TROP_VOLUMINEUX. */
export function useExporterJournal() {
  return useMutation({
    mutationFn: (filtres: FiltresJournal) =>
      api.get<Blob>("/audit/export.xlsx", { params: paramsFiltres(filtres), reponse: "blob" }),
  });
}
