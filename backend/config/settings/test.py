"""Tests automatisés (pytest-django ; service compose « tests »)."""

from .base import *  # noqa: F403

# B1 : alpha_app n'a pas CREATEDB ; la base de test est donc créée et migrée par
# alpha_owner (DATABASE_URL_OWNER). La tâche T1 remplacera ce choix provisoire par
# la bascule de la connexion « default » sur alpha_app après migration et par
# l'alias « proprietaire » (§ 8, T1).
if ALPHA_DATABASE_URL_OWNER:  # noqa: F405
    DATABASES["default"] = {  # noqa: F405
        **env.db_url_config(ALPHA_DATABASE_URL_OWNER),  # noqa: F405
        "CONN_MAX_AGE": 0,
        "ATOMIC_REQUESTS": True,
    }

# HTTP dans le client de test : cookies sans Secure pour pouvoir les relire.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

ALPHA_DOC_API_ACTIVE = True
# Pas de proxy devant le client de test.
ALPHA_NB_PROXIES_CONFIANCE = 0

# Tâches Celery exécutées dans le processus de test (pas de worker dans le service « tests »).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# E-mails : Mailpit si disponible (service compose), sinon mémoire.
if env("ALPHA_MAILPIT_API", default=None) is None:  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
