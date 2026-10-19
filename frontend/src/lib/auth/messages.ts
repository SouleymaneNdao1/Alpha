/**
 * Messages d'erreur des écrans d'authentification, en français, pour chaque
 * code du contrat (B5 livré, § 5.2 pour B6). Le message du serveur sert de
 * repli pour un code inconnu.
 */
import { estApiError } from "@/lib/api/erreurs";

export type ContexteAuth =
  | "connexion"
  | "mfa"
  | "activation"
  | "reenrolement"
  | "reinitialisation"
  | "oubli"
  | "telephone-perdu";

function details(e: { details: unknown }): Record<string, unknown> {
  return e.details && typeof e.details === "object" ? (e.details as Record<string, unknown>) : {};
}

/** « 45 secondes », « 1 minute », « 14 minutes ». */
export function duree(secondes: number): string {
  const s = Math.max(1, Math.ceil(secondes));
  if (s < 60) return `${s} seconde${s > 1 ? "s" : ""}`;
  const m = Math.ceil(s / 60);
  return `${m} minute${m > 1 ? "s" : ""}`;
}

const heure = (d: Date) => d.toLocaleTimeString("fr-SN", { hour: "2-digit", minute: "2-digit" });

/** Message pour COMPTE_VERROUILLE : durée restante et heure de fin, ou déblocage par l'administrateur. */
export function messageVerrouillage(d: Record<string, unknown>, maintenant = new Date()): string {
  const jusqua = typeof d.jusqua === "string" ? new Date(d.jusqua) : null;
  if (d.deblocage_administrateur === true || !jusqua || Number.isNaN(jusqua.getTime())) {
    return "Votre compte est bloqué après plusieurs verrouillages. Contactez votre administrateur pour le débloquer.";
  }
  const restant = (jusqua.getTime() - maintenant.getTime()) / 1000;
  if (restant <= 0) return "Votre compte était verrouillé. Vous pouvez réessayer maintenant.";
  return `Trop d'essais : votre compte est verrouillé pendant ${duree(restant)} (jusqu'à ${heure(jusqua)}).`;
}

export function messageErreurAuth(erreur: unknown, contexte: ContexteAuth): string {
  if (!estApiError(erreur)) return "Une erreur inattendue s'est produite. Réessayez.";
  const d = details(erreur);
  // Un 410 concerne toujours un lien (jeton) expiré, quel que soit le code.
  const code = erreur.status === 410 ? "JETON_INVALIDE" : erreur.code;
  switch (code) {
    case "IDENTIFIANTS_INVALIDES":
      if (contexte === "reenrolement") return "Mot de passe incorrect.";
      return "Adresse e-mail ou mot de passe incorrect. Après 5 essais, le compte est verrouillé pendant 15 minutes.";
    case "ETABLISSEMENT_SUSPENDU":
      return "L'accès de votre établissement à ALPHA est suspendu. Contactez votre administrateur.";
    case "TROP_DE_REQUETES": {
      const s = typeof d.reessayer_dans_s === "number" ? d.reessayer_dans_s : null;
      return s ? `Trop de tentatives. Réessayez dans ${duree(s)}.` : "Trop de tentatives. Patientez quelques minutes avant de réessayer.";
    }
    case "CODE_INVALIDE": {
      const n = typeof d.tentatives_restantes === "number" ? d.tentatives_restantes : null;
      const base =
        contexte === "mfa" || contexte === "reinitialisation"
          ? "Code incorrect ou expiré."
          : "Code incorrect. Vérifiez l'heure de votre téléphone et saisissez le code affiché.";
      if (n === null) return base;
      return `${base} Il vous reste ${n} essai${n > 1 ? "s" : ""}.`;
    }
    case "PREAUTH_EXPIREE":
      return "Votre demande de connexion a expiré (5 minutes). Saisissez de nouveau votre mot de passe.";
    case "COMPTE_VERROUILLE":
      return messageVerrouillage(d);
    case "SESSION_EXPIREE":
      return "Votre session a expiré. Reconnectez-vous.";
    case "JETON_INVALIDE":
      return contexte === "reinitialisation"
        ? "Ce lien de réinitialisation n'est plus valide (il expire après 30 minutes ou après usage). Demandez-en un nouveau."
        : contexte === "reenrolement"
          ? "Ce lien de réenrôlement n'est plus valide. Demandez à votre administrateur de vous en envoyer un nouveau."
          : "Ce lien d'invitation n'est plus valide ou a expiré. Demandez à votre administrateur de vous renvoyer une invitation.";
    case "ETAPE_INVALIDE":
      return "Cette étape n'est plus disponible. Rouvrez le lien reçu par e-mail pour reprendre.";
    case "CSRF_INVALIDE":
      return "La page a expiré. Rechargez-la puis réessayez.";
    case "NON_AUTHENTIFIE":
      return contexte === "reenrolement" ? "Mot de passe incorrect." : erreur.message;
    case "VALIDATION":
      return "Certains champs sont invalides. Corrigez-les puis réessayez.";
    default:
      return erreur.message || "Une erreur inattendue s'est produite. Réessayez.";
  }
}
