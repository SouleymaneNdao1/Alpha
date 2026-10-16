import { NextResponse, type NextRequest } from "next/server";

/**
 * Contrôle de confort (architecture § 7.4) : une route des groupes `(app)` ou
 * `(console)` sans cookie de session `alpha_sid` est redirigée vers
 * `/connexion?suivant=<route>`. La vraie vérification est faite par
 * `GET /auth/session` dans le layout (le cookie peut exister mais être expiré).
 */
export const COOKIE_SESSION = "alpha_sid";

export function middleware(requete: NextRequest) {
  if (requete.cookies.has(COOKIE_SESSION)) return NextResponse.next();
  const { pathname, search } = requete.nextUrl;
  const cible = new URL(`/connexion?suivant=${encodeURIComponent(pathname + search)}`, originepublique(requete));
  return NextResponse.redirect(cible, 307);
}

/**
 * Origine vue par le navigateur. Le serveur standalone construit `nextUrl` avec
 * son propre nom d'hôte (ex. http://localhost:3000) : derrière Caddy, la
 * redirection enverrait l'utilisateur vers une adresse interne. On reprend donc
 * l'hôte et le protocole transmis par le proxy (ou l'en-tête Host).
 */
function originepublique(requete: NextRequest): string {
  const premier = (v: string | null) => v?.split(",")[0]?.trim() || null;
  const hote = premier(requete.headers.get("x-forwarded-host")) ?? premier(requete.headers.get("host"));
  const proto = premier(requete.headers.get("x-forwarded-proto")) ?? requete.nextUrl.protocol.replace(":", "");
  return hote ? `${proto}://${hote}` : requete.nextUrl.origin;
}

/** Routes des groupes (app) et (console) — architecture § 7.1. */
export const config = {
  matcher: [
    "/a-traiter/:path*",
    "/mon-compte/:path*",
    "/absences/:path*",
    "/administration/:path*",
    "/journal/:path*",
    "/console/:path*",
  ],
};
