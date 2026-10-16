import type { NextConfig } from "next";

/**
 * ALPHA — configuration Next.js (architecture § 1 et § 1.3).
 *
 * - Sortie « standalone » : l'image de production lance `node server.js` (tâche D3).
 * - En dev, le navigateur ne parle qu'à http://localhost:3000 ; `/api/*` est
 *   réécrit vers le backend Django (ALPHA_BACKEND_URL, posée par docker-compose).
 *   En recette et production, Caddy route `/api/*` directement vers le backend :
 *   ces réécritures ne servent alors plus (même origine, cookies SameSite=Lax).
 *
 * Les URL Django se terminent par « / » (ex. /api/v1/schema/). Par défaut, Next
 * redirige `/x/` vers `/x` AVANT les réécritures, ce qui casserait les POST :
 * on désactive cette redirection et la règle avec « / » final passe en premier.
 */
const backend = (process.env.ALPHA_BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      { source: "/api/:chemin*/", destination: `${backend}/api/:chemin*/` },
      { source: "/api/:chemin*", destination: `${backend}/api/:chemin*` },
    ];
  },
};

export default nextConfig;
