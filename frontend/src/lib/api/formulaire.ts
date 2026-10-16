import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { estApiError } from "./erreurs";

/**
 * Reporte une erreur VALIDATION de l'API sur les champs d'un formulaire
 * react-hook-form. Renvoie le message global à afficher (erreurs hors champ,
 * ou message de l'ApiError), ou `null` si tout a été rattaché à des champs.
 */
export function appliquerErreursApi<T extends FieldValues>(
  erreur: unknown,
  setError: UseFormSetError<T>,
  champsConnus: readonly Path<T>[],
): string | null {
  if (!estApiError(erreur)) return "Une erreur inattendue s'est produite.";
  if (!erreur.estValidation) return erreur.message;
  const restants: string[] = [];
  for (const [champ, messages] of Object.entries(erreur.erreursDeChamps)) {
    if ((champsConnus as readonly string[]).includes(champ)) {
      setError(champ as Path<T>, { type: "serveur", message: messages.join(" ") });
    } else {
      restants.push(...messages);
    }
  }
  return restants.length ? restants.join(" ") : null;
}
