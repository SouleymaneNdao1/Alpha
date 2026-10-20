"use client";

/**
 * Notifications (cloche du bandeau, F2 puis F6) :
 * `GET /moi/notifications?non_lues=1&taille=` → page + `non_lues`, `POST /moi/notifications/{id}/lue`
 * → 204, `POST /moi/notifications/tout-lu` → 204. Contrat : `alpha/notifications/serializers.py`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import type { Schema } from "../types";

export type Notification = Schema<"Notification">;
export type PageNotifications = Schema<"PageNotifications">;

const RACINE = ["moi", "notifications"] as const;

/** Compteur de la cloche : interrogé toutes les 60 s en appel de fond. Une erreur masque simplement le compteur. */
export function useNotificationsNonLues(options: { active?: boolean } = {}) {
  return useQuery({
    queryKey: [...RACINE, "non-lues"],
    queryFn: async ({ signal }) => {
      const r = await api.get<{ non_lues?: number }>("/moi/notifications", { signal, fond: true, params: { non_lues: 1, taille: 1 } });
      return typeof r?.non_lues === "number" ? r.non_lues : 0;
    },
    enabled: options.active ?? true,
    refetchInterval: 60_000,
    retry: false,
  });
}

/** Liste des notifications, les plus récentes d'abord (panneau de la cloche : 10 ; Mon compte : 25). */
export function useNotifications(options: { taille: number; active?: boolean }) {
  return useQuery({
    queryKey: [...RACINE, "liste", options.taille],
    queryFn: ({ signal }) => api.get<PageNotifications>("/moi/notifications", { signal, params: { taille: options.taille } }),
    enabled: options.active ?? true,
    retry: false,
  });
}

export function useMarquerLue() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<void>(`/moi/notifications/${encodeURIComponent(id)}/lue`),
    onSettled: () => void client.invalidateQueries({ queryKey: RACINE }),
  });
}

export function useToutMarquerLu() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/moi/notifications/tout-lu"),
    onSettled: () => void client.invalidateQueries({ queryKey: RACINE }),
  });
}
