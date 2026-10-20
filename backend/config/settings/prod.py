"""Production (VPS, derrière Caddy en HTTPS).

Caddy termine TLS, redirige HTTP vers HTTPS et ajoute X-Forwarded-Proto ; il pose
aussi HSTS et CSP (tâche D3). Django pose HSTS en complément.
"""

from .base import *  # noqa: F403

DEBUG = False

# Obligatoire en recette/prod : aucune valeur par défaut.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Caddy est le seul point d'entrée : le schéma d'origine est lu dans X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# La redirection HTTP -> HTTPS est faite par Caddy. Ne pas la refaire dans Django :
# les sondes internes (healthcheck compose sur http://127.0.0.1:8000) seraient redirigées.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = env.int("ALPHA_HSTS_SECONDES", default=31_536_000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = env.bool("ALPHA_HSTS_PRELOAD", default=False)  # noqa: F405

SILENCED_SYSTEM_CHECKS = [
    # security.W008 (SECURE_SSL_REDIRECT) : redirection assurée par Caddy, voir ci-dessus.
    "security.W008",
]
if not SECURE_HSTS_PRELOAD:
    # security.W021 : l'inscription à la liste de préchargement HSTS est une décision
    # du titulaire du domaine (irréversible à court terme) ; activable par ALPHA_HSTS_PRELOAD.
    SILENCED_SYSTEM_CHECKS.append("security.W021")

# Production : ni schéma OpenAPI ni documentation ne sont routés (404).
ALPHA_DOC_API_ACTIVE = False
ALPHA_DOC_API_RESERVEE_CONNECTES = True

# Jeu de démonstration : JAMAIS en production (manage.py semer_demo refuse de s'exécuter).
ALPHA_DEMO_AUTORISEE = False
