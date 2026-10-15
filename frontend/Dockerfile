# =============================================================================
# ALPHA — image frontend (Next.js). Architecture § 1 : node:22-alpine (décision du 15/10 : Node 22 LTS).
#
# Étapes :
#   base   : Node + variables communes
#   deps   : node_modules installés DANS l'image (jamais montés depuis l'hôte)
#   dev    : `next dev` ; le code est monté en volume, node_modules et .next
#            restent des volumes anonymes du conteneur (docker-compose.override.yml)
#   (prod) : build "standalone" + `node server.js`, ajoutée par la tâche D3
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
