# =============================================================================
# ALPHA — image frontend (Next.js). Architecture § 1 : node:22-alpine (décision du 15/10 : Node 22 LTS).
#
# Étapes :
#   base   : Node + variables communes
#   deps   : node_modules installés DANS l'image (jamais montés depuis l'hôte)
#   dev    : `next dev` ; le code est monté en volume, node_modules et .next
#            restent des volumes anonymes du conteneur (docker-compose.override.yml)
#   build  : `next build` (sortie « standalone », next.config.ts) — tâche D3
#   prod   : serveur standalone `node server.js`, utilisateur `node`, sans
#            node_modules complets ni code source — tâche D3
#
# Attention : les réécritures /api de next.config.ts sont FIGÉES au build
# (ALPHA_BACKEND_URL ci-dessous). En recette et en production, Caddy route
# /api/* directement vers le backend ; la réécriture ne sert que de filet.
# L'image ne contient aucune valeur propre à un environnement : la même image
# passe de la recette à la production.
# =============================================================================

ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1 \
    TZ=Africa/Dakar
WORKDIR /app

# --- Dépendances --------------------------------------------------------------
FROM base AS deps
COPY package.json package-lock.json* ./
# npm ci si le verrou existe (à partir de F1), sinon npm install.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# --- Développement ------------------------------------------------------------
FROM base AS dev
# L'utilisateur `node` (UID 1000) de l'image correspond à l'utilisateur WSL par défaut.
# Les répertoires des volumes anonymes doivent exister et lui appartenir dans
# l'image, sinon Docker les crée au nom de root.
RUN mkdir -p /app/node_modules /app/.next && chown -R node:node /app
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
USER node
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

# --- Build de production (tâche D3) -------------------------------------------
FROM deps AS build
ARG ALPHA_BACKEND_URL=http://backend:8000
ENV ALPHA_BACKEND_URL=${ALPHA_BACKEND_URL} \
    NODE_ENV=production
COPY . .
# Le dossier public/ est facultatif : on le crée pour que l'étape prod puisse le copier.
RUN mkdir -p public \
 && npm run build

# --- Production (tâche D3) ----------------------------------------------------
FROM base AS prod
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
# Sortie standalone : server.js + le strict nécessaire de node_modules.
# Fichiers en lecture seule pour l'utilisateur `node` (propriété de root).
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
# Cache d'images/ISR de Next : seul répertoire inscriptible.
RUN mkdir -p .next/cache && chown node:node .next/cache
USER node
EXPOSE 3000
CMD ["node", "server.js"]
