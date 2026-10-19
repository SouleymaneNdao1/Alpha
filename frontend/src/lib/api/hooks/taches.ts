"use client";

/**
 * Hooks de l'écran « À traiter » (F5) : `GET /taches/` (page, triée groupe puis
 * échéance) et `GET /taches/compteurs/`. Contrat réel : serializers du backend
 * (`alpha/taches/serializers.py`).
 */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "../client";
import type { Page } from "../types";

export type GroupeTache = "EN_RETARD" | "AUJOURDHUI" | "CETTE_SEMAINE" | "PLUS_TARD";
export const GROUPES: readonly GroupeTache[] = ["EN_RETARD", "AUJOURDHUI", "CETTE_SEMAINE", "PLUS_TARD"];

export type ActionTache = "DECIDER" | "SIGNER" | "VALIDER" | "COMPLETER" | "TRAITER";

export interface Tache {
  id: string;
  module: string;
  module_libelle: string;
  reference: string;
  titre: string;
  sous_titre: string;
  /** Décimal sérialisé en chaîne (« 14600000.00 »). */
  montant: string | null;
  devise: string;
  action: ActionTache;
  action_libelle: string;
  type_echeance: string;
  echeance: string | null;
  groupe: GroupeTache;
  retard_jours: number | null;
  lien: string;
  par_delegation_de: { id: string; nom: string } | null;
  cree_le: string;
}

export interface CompteursTaches {
  total: number;
  par_groupe: Record<GroupeTache, number>;
  par_module: Record<string, number>;
}

/** Libellés des modules (`Module` du backend) : les compteurs ne renvoient que les codes. */
export const LIBELLES_MODULES: Record<string, string> = {
  COMPTE: "Mon compte",
  ADMINISTRATION: "Administration",
  CREDIT: "Crédit",
  INTERNE: "Décisions internes",
  RH: "Ressources humaines",
  TRESORERIE: "Trésorerie",
  CONTRATS: "Contrats",
  GOUVERNANCE: "Gouvernance",
  FISCAL: "Fiscalité",
  PME_FOURNISSEURS: "Fournisseurs",
  PME_BUDGET: "Budget",
  PME_COMMERCIAL: "Commercial",
};

export const INTERVALLE_COMPTEURS_MS = 60_000;

export const CLE_COMPTEURS = ["taches", "compteurs"] as const;

/** Compteurs, actualisés toutes les 60 s en appel de fond (n'étend pas l'inactivité). */
export function useCompteursTaches(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: CLE_COMPTEURS,
    queryFn: ({ signal }) => api.get<CompteursTaches>("/taches/compteurs/", { signal, fond: true }),
    enabled: options.active ?? true,
    refetchInterval: INTERVALLE_COMPTEURS_MS,
    staleTime: 15_000,
    retry: false,
  });
}

export interface FiltresTaches {
  module: string | null;
  groupe: GroupeTache | null;
}

export const TAILLE_PAGE_TACHES = 100;

/**
 * Tâches (pages de 100, « Afficher plus » pour la suite). `fond()` indique si
 * la requête est une actualisation automatique (X-Alpha-Fond) ou une action
 * de l'utilisateur.
 */
export function useTaches(filtres: FiltresTaches, fond: () => boolean) {
  return useInfiniteQuery({
    queryKey: ["taches", "liste", filtres.module, filtres.groupe],
    initialPageParam: 1,
    queryFn: ({ signal, pageParam }) =>
      api.get<Page<Tache>>("/taches/", {
        signal,
        fond: fond(),
        params: { module: filtres.module, groupe: filtres.groupe, page: pageParam, taille: TAILLE_PAGE_TACHES },
      }),
    getNextPageParam: (derniere, _pages, pageCourante) => (derniere.next ? pageCourante + 1 : undefined),
    retry: false,
  });
}
