"""Tests automatisés (pytest-django ; service compose « tests »)."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

# --- Connexions (tâche T1, § 8) -------------------------------------------------------------
# - « default »      : alpha_app (DATABASE_URL), soumis à la RLS. Les tests s'exécutent
#                      sous ce rôle. alpha_app n'a pas CREATEDB : la base de test est
#                      créée et migrée par alpha_owner (bascule temporaire des
#                      identifiants de « default », voir tests/conftest.py), puis
#                      « default » repasse en alpha_app avant le premier test ;
# - « proprietaire » : alpha_owner (DATABASE_URL_OWNER), miroir de la même base.
#                      RÉSERVÉ aux tests qui contournent volontairement les protections
#                      (altération du journal d'audit, lecture hors RLS) ; il sert aussi
#                      au vidage des tests transactionnels ;
# - « audit »        : alpha_app, miroir (connexion indépendante du journal, B4).
# Une connexion ne voit que les données VALIDÉES par une autre : un test qui mélange
# « default » et « proprietaire » (ou « audit ») est transactionnel.
if not ALPHA_DATABASE_URL_OWNER:  # noqa: F405
    raise ImproperlyConfigured(
        "Les tests exigent DATABASE_URL_OWNER (alpha_owner) : il crée et migre la base de test."
    )

DATABASES["default"].update(  # noqa: F405
    {"CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False, "ATOMIC_REQUESTS": True}
)
DATABASES["proprietaire"] = {  # noqa: F405
    **env.db_url_config(ALPHA_DATABASE_URL_OWNER),  # noqa: F405
    "CONN_MAX_AGE": 0,
    "ATOMIC_REQUESTS": False,
    "TEST": {"MIRROR": "default"},
}
DATABASES["audit"] = {  # noqa: F405
    **DATABASES["default"],  # noqa: F405
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

# Adresse sécurité FYXOP fictive (ancrage et alertes du journal d'audit).
ALPHA_EMAIL_SECURITE_FYXOP = "securite@fyxop.test"

# Tâches Celery exécutées dans le processus de test (pas de worker dans le service « tests »).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# E-mails : backend en mémoire pour tous les tests (mail.outbox), service compose compris.
# Les tests qui vérifient l'acheminement réel demandent la fixture « mailpit »
# (tests/mailpit.py) : SMTP vers Mailpit s'il répond, sinon le test est sauté.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# SMTP de Mailpit (service compose : EMAIL_HOST=mailpit ; hors docker : 127.0.0.1).
EMAIL_HOST = env("EMAIL_HOST", default="127.0.0.1")  # noqa: F405
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)  # noqa: F405
# API HTTP de Mailpit (racine /api/v1) ; identifiants si Mailpit est protégé (P11).
ALPHA_MAILPIT_API = env("ALPHA_MAILPIT_API", default="http://127.0.0.1:8025/api/v1")  # noqa: F405
ALPHA_MAILPIT_UTILISATEUR = env("ALPHA_MAILPIT_UTILISATEUR", default="")  # noqa: F405
ALPHA_MAILPIT_MOT_DE_PASSE = env("ALPHA_MAILPIT_MOT_DE_PASSE", default="")  # noqa: F405
