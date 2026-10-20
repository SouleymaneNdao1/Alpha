/**
 * Destination après une connexion réussie : `?suivant=` s'il désigne une route
 * interne de l'application, sinon `/a-traiter` (ou `/console` pour un
 * super-admin, § 4.2 étape 13). Une URL absolue ou « //hote » est refusée
 * (redirection ouverte).
 */
export const ACCUEIL = "/a-traiter";
export const ACCUEIL_CONSOLE = "/console";
/** La console FYXOP (F9) existe : un super-admin est dirigé vers `/console` après la connexion. */
const CONSOLE_DISPONIBLE = true;

const ROUTES_AUTH = ["/connexion", "/activation", "/reenrolement", "/mot-de-passe-oublie", "/reinitialisation"];

export function destinationSure(suivant: string | null | undefined): string | null {
  if (!suivant || !suivant.startsWith("/") || suivant.startsWith("//") || suivant.includes("\\")) return null;
  try {
    const url = new URL(suivant, "http://alpha.invalid");
    if (url.origin !== "http://alpha.invalid") return null;
    if (ROUTES_AUTH.some((r) => url.pathname === r || url.pathname.startsWith(`${r}/`))) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}

export function destinationApresConnexion(suivant: string | null | undefined, estSuperAdmin: boolean): string {
  return destinationSure(suivant) ?? (estSuperAdmin && CONSOLE_DISPONIBLE ? ACCUEIL_CONSOLE : ACCUEIL);
}
