"""Développement local (docker-compose.override.yml) : HTTP, Mailpit, documentation active."""

from .base import *  # noqa: F403

DEBUG = True

# Le poste de développement est en HTTP : cookies sans l'attribut Secure.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

ALPHA_DOC_API_ACTIVE = True

# Requêtes SQL visibles avec ALPHA_NIVEAU_JOURNAL=DEBUG.
LOGGING["loggers"]["django.db.backends"]["level"] = env(  # noqa: F405
    "ALPHA_NIVEAU_JOURNAL_SQL", default="WARNING"
)
