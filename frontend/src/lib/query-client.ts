import { QueryClient } from "@tanstack/react-query";
import { estApiError } from "./api/erreurs";

/**
 * Réglages TanStack Query communs. On ne réessaie pas une erreur 4xx (droits,
 * validation, session expirée…) : seulement le réseau et les 5xx, deux fois.
 */
export function creerQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (essais, erreur) => {
          if (estApiError(erreur) && erreur.status >= 400 && erreur.status < 500) return false;
          return essais < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}
