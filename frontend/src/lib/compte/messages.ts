import { estApiError } from "@/lib/api/erreurs";

/** Erreur portant sur le code TOTP saisi (affichée sous les cases, pas dans le bandeau d'erreur). */
export function estErreurCode(e: unknown): boolean {
  return estApiError(e) && (e.code === "CODE_INVALIDE" || e.code === "TROP_DE_REQUETES");
}

function detailEntier(e: unknown, cle: string): number | null {
  if (!estApiError(e) || typeof e.details !== "object" || e.details === null) return null;
  const v = (e.details as Record<string, unknown>)[cle];
  return typeof v === "number" ? v : null;
}

/** Message français d'une erreur d'API pour les actions de Mon compte et de l'administration. */
export function messageErreur(e: unknown): string {
  if (!estApiError(e)) return "Une erreur inattendue s'est produite.";
  switch (e.code) {
    case "CODE_INVALIDE": {
      const n = detailEntier(e, "tentatives_restantes");
      return `Code invalide ou expiré. Vérifiez l'heure de votre téléphone puis saisissez le code affiché.${n !== null ? ` Il vous reste ${n} essai${n > 1 ? "s" : ""}.` : ""}`;
    }
    case "MOT_DE_PASSE_INCORRECT": {
      const n = detailEntier(e, "tentatives_restantes");
      return `Mot de passe actuel incorrect.${n !== null ? ` Il vous reste ${n} essai${n > 1 ? "s" : ""}.` : ""}`;
    }
    case "TROP_DE_REQUETES": {
      const s = detailEntier(e, "reessayer_dans_s");
      return `Trop de tentatives. Patientez${s ? ` ${s} secondes` : " un instant"} avant de réessayer.`;
    }
    case "DERNIER_ADMINISTRATEUR":
      return "Opération impossible : il doit rester au moins un administrateur actif dans l'établissement. Attribuez d'abord le droit « Utilisateurs » (rôle Administrateur ALPHA) à une autre personne active, puis recommencez.";
    case "AUTO_TRAITEMENT_INTERDIT": {
      const recours = typeof e.details === "object" && e.details !== null && (e.details as Record<string, unknown>).recours_fyxop === true;
      return `Vous ne pouvez pas traiter votre propre signalement : un autre administrateur doit vérifier votre identité.${recours ? " Aucun autre administrateur n'est disponible : la direction de votre établissement doit adresser une demande écrite signée à FYXOP." : ""}`;
    }
    case "VALIDATION": {
      const champs = e.erreursDeChamps;
      const textes = Object.entries(champs).flatMap(([, m]) => m);
      return textes.length ? textes.join(" ") : e.message;
    }
    default:
      return e.message;
  }
}
