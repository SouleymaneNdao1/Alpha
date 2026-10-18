# =============================================================================
# ALPHA — image backend (Django, Celery). Architecture § 1 : python:3.12-slim,
# multi-stage, utilisateur non root.
#
# Étapes :
#   base     : Python + variables communes
#   deps     : environnement virtuel /opt/venv avec les dépendances d'exécution
#   dev      : + dépendances de dev/test ; le code est MONTÉ en volume (/app)
#   prod-deps: environnement virtuel de PRODUCTION, installé depuis
#              requirements.lock avec --require-hashes (tâche D3)
#   prod     : code copié (propriété de root, en lecture seule), gunicorn,
#              utilisateur non root `alpha` (UID 10001), sans outils de dev
#
# Construire l'image de production :
#   docker build --target prod -t alpha-backend:<version> backend/
# (scripts/deploy.sh le fait via docker-compose.recette.yml / prod.yml).
#
# En développement, les dépendances sont lues dans pyproject.toml
# ([project.dependencies] et [project.optional-dependencies].dev) : la couche
# n'est reconstruite que si ce fichier change. En production, elles viennent
# EXCLUSIVEMENT de requirements.lock (versions et empreintes figées).
# =============================================================================

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    TZ=Africa/Dakar

# --- Dépendances d'exécution --------------------------------------------------
FROM base AS deps
COPY pyproject.toml /tmp/pyproject.toml
RUN python -c "import tomllib; p = tomllib.load(open('/tmp/pyproject.toml', 'rb'))['project']; open('/tmp/requirements.txt', 'w').write('\n'.join(p['dependencies']) + '\n'); open('/tmp/requirements-dev.txt', 'w').write('\n'.join(p.get('optional-dependencies', {}).get('dev', [])) + '\n')" \
 && python -m venv /opt/venv \
 && pip install -r /tmp/requirements.txt

# --- Développement ------------------------------------------------------------
FROM deps AS dev
ARG UID=1000
ARG GID=1000
RUN pip install -r /tmp/requirements-dev.txt \
 && (getent group "${GID}" >/dev/null || groupadd --gid "${GID}" alpha) \
 && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /bin/bash alpha \
 && mkdir -p /app \
 && chown "${UID}:${GID}" /app
WORKDIR /app
USER alpha
EXPOSE 8000
# Remplacée par `command:` dans docker-compose ; utile pour un `docker run` isolé.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --- Production : dépendances (tâche D3) --------------------------------------
# Installation reproductible et vérifiée : chaque paquet doit correspondre à une
# empreinte SHA-256 du verrou (--require-hashes), uniquement des roues binaires
# (--only-binary : aucun code de construction exécuté), sans résolution
# (--no-deps : le verrou est complet). Aucun outil de dev/test dans l'image.
FROM base AS prod-deps
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv \
 && pip install --no-deps --require-hashes --only-binary=:all: -r /tmp/requirements.lock \
 && pip check \
 && rm /tmp/requirements.lock

# --- Production : image finale (tâche D3) -------------------------------------
FROM base AS prod
# Utilisateur système non root, sans shell de connexion. UID/GID fixes (10001)
# pour que les droits du volume média soient stables d'une image à l'autre.
RUN groupadd --system --gid 10001 alpha \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home \
            --shell /usr/sbin/nologin alpha
COPY --from=prod-deps /opt/venv /opt/venv
WORKDIR /app
# Le code appartient à root : le processus applicatif ne peut pas le modifier.
COPY . /app
# Bytecode précompilé (PYTHONDONTWRITEBYTECODE empêche de l'écrire à l'exécution) ;
# /app/media : seul répertoire inscriptible (volume « media », sauvegardé).
RUN python -m compileall -q /app \
 && mkdir -p /app/media \
 && chown alpha:alpha /app/media
ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    ALPHA_MEDIA_ROOT=/app/media
USER alpha
EXPOSE 8000
# Remplacée par `command:` dans les fichiers compose ; valeur sûre par défaut.
# Pas de journal d'accès gunicorn : Caddy le tient déjà, en masquant les jetons des URL.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--forwarded-allow-ips", "*"]
