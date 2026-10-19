"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../client";

/**
 * Compteur de la cloche : `GET /moi/notifications?non_lues=1` → page + `non_lues`
 * (architecture § 5). L'endpoint n'est pas encore livré par le backend : une
 * erreur masque simplement le compteur (la cloche reste utilisable).
 */
export function useNotificationsNonLues(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: ["moi", "notifications", "non-lues"],
    queryFn: async ({ signal }) => {
      const r = await api.get<{ non_lues?: number }>("/moi/notifications", { signal, fond: true, params: { non_lues: 1, taille: 1 } });
      return typeof r?.non_lues === "number" ? r.non_lues : 0;
    },
    enabled: options.active ?? true,
    refetchInterval: 60_000,
    retry: false,
  });
}
