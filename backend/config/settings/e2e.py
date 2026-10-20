"""Tests de bout en bout avec le vrai backend (tâche T5, suite ``frontend/e2e-integration``).

Réglages DÉDIÉS à cette suite : ils ne servent ni en développement ni en recette ni en
production, et ne modifient aucun de ces environnements.

- HTTP local : cookies sans l'attribut Secure ;
- jeu de démonstration autorisé (``manage.py semer_demo`` prépare les comptes) ;
- pas de Mailpit : les e-mails sont écrits dans un dossier (backend « fichier » de Django),
  que la suite relit pour suivre les liens d'invitation et de réenrôlement ;
- pas de worker Celery : les tâches s'exécutent dans le processus du serveur de test ;
- un seul proxy de confiance (le proxy de test qui joue le rôle de Caddy et pose
  ``X-Forwarded-For``).
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

ALPHA_DOC_API_ACTIVE = True
ALPHA_DEMO_AUTORISEE = True

# E-mails : un fichier par connexion SMTP simulée, dans le dossier désigné par l'environnement.
_dossier_courriels = env("ALPHA_E2E_DOSSIER_EMAILS", default="")  # noqa: F405
if not _dossier_courriels:
    raise ImproperlyConfigured(
        "ALPHA_E2E_DOSSIER_EMAILS est obligatoire avec config.settings.e2e : dossier où "
        "les e-mails sont écrits."
    )
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = _dossier_courriels

# Pas de worker : exécution immédiate des tâches (envoi des e-mails compris).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

ALPHA_NB_PROXIES_CONFIANCE = 1
ALPHA_EMAIL_SECURITE_FYXOP = "securite@fyxop.test"
