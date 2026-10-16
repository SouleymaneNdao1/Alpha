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
    # B2 : connexion « applicatif » en alpha_app (DATABASE_URL) sur la MÊME base
    # de test (miroir de « default », donc jamais créée ni vidée par elle), pour
    # vérifier la RLS et les droits du rôle applicatif. Les tests qui l'utilisent
    # sont transactionnels (les données posées par « default » doivent être
    # validées pour être visibles d'une autre connexion).
    # T1 remplacera ce montage par la bascule de « default » sur alpha_app.
    DATABASES["applicatif"] = {  # noqa: F405
        **env.db_url_config(env("DATABASE_URL")),  # noqa: F405
        "CONN_MAX_AGE": 0,
        "ATOMIC_REQUESTS": False,
        "TEST": {"MIRROR": "default"},
    }

# Application réservée aux tests : modèle tenant générique (NoteTest) avec sa RLS.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.appli_test"]  # noqa: F405

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
