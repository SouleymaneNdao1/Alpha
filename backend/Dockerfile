# =============================================================================
# ALPHA — image backend (Django, Celery). Architecture § 1 : python:3.12-slim,
# multi-stage, utilisateur non root.
#
# Étapes :
#   base     : Python + variables communes
#   deps     : environnement virtuel /opt/venv avec les dépendances d'exécution
#   dev      : + dépendances de dev/test ; le code est MONTÉ en volume (/app)
#   (prod)   : ajoutée par la tâche D3 (code copié, gunicorn, sans outils de dev)
#
# Les dépendances sont lues dans pyproject.toml ([project.dependencies] et
# [project.optional-dependencies].dev) : la couche n'est reconstruite que si ce
# fichier change.
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
