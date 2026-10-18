"""Réglages communs à tous les environnements (dev, test, recette, prod).

Toutes les valeurs propres à un déploiement viennent des variables
d'environnement (voir .env.example et docker-compose.yml). Une variable
obligatoire absente fait échouer le démarrage avec ImproperlyConfigured.
"""

from pathlib import Path

import environ
from celery.schedules import crontab
from kombu import Queue

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# --- Sécurité de base ------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "backend"])

# --- Applications (architecture § 1.1) ----------------------------------------------
# django.contrib.admin n'est PAS installé (il contournerait le contexte tenant).
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "alpha.core",
    "alpha.tenancy",
    "alpha.comptes",
    "alpha.organisation",
    "alpha.delegations",
    "alpha.taches",
    "alpha.notifications",
    "alpha.audit",
    "alpha.plateforme",
]

# --- Middlewares (ordre du § 3.3) ---------------------------------------------------
# À ajouter par la tâche B5, à sa place :
#   alpha.comptes.middleware.SessionActiviteMiddleware  après AuthenticationMiddleware,
#   avant StatutEtablissementMiddleware.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "alpha.core.middleware.RequestIdMiddleware",
    # Ouvre la transaction la plus externe et pose le contexte tenant (B2).
    "alpha.tenancy.middleware.TenantContextMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # SUSPENDU → 403, LECTURE_SEULE → 423 sur écriture (B2).
    "alpha.tenancy.middleware.StatutEtablissementMiddleware",
    # En-tête X-Frame-Options (anti-clickjacking), en complément de Caddy.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Gabarits : pages de documentation de l'API, puis gabarits d'e-mails (B6).
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

# --- Base de données (§ 3.1, § 3.2, § 3.3) ------------------------------------------
# DATABASE_URL : alpha_app pour backend/worker/beat ; alpha_owner pour le service migrate.
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"].update(
    {
        # Les variables app.* sont posées en local à la transaction : pas de fuite
        # d'un établissement à l'autre via une connexion persistante.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        # La vue tourne dans un point de sauvegarde imbriqué dans la transaction
        # ouverte par TenantContextMiddleware (B2).
        "ATOMIC_REQUESTS": True,
    }
)
# Connexion indépendante du journal d'audit (B4) : même base et même rôle que
# « default », mais hors de la transaction de la requête. Utilisée seulement par
# journaliser(..., hors_transaction=True), pour un événement qui doit survivre à
# l'annulation de la transaction appelante (§ 3.3, § 6.1).
DATABASES["audit"] = {
    **DATABASES["default"],
    "ATOMIC_REQUESTS": False,
    "TEST": {"MIRROR": "default"},
}
ALPHA_AUDIT_ALIAS_INDEPENDANT = "audit"
# Rôle applicatif injecté dans les RunSQL (GRANT, politiques RLS) : § 3.1.
ALPHA_DB_APP_ROLE = env("ALPHA_DB_APP_ROLE", default="alpha_app")
# Connexion propriétaire (alpha_owner) : uniquement migrate, tests et exploitation.
ALPHA_DATABASE_URL_OWNER = env("DATABASE_URL_OWNER", default=None)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache et sessions (§ 1.3, § 4.1) -----------------------------------------------
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "alpha",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = "alpha_sid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_PATH = "/"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Plafond technique de la session Django : 24 h, valeur maximale autorisée pour
# ParametresEtablissement.duree_max_session_h (P2, réglable de 1 à 24 h, 12 h par
# défaut). L'inactivité et la durée maximale propres à chaque établissement sont
# contrôlées par SessionActiviteMiddleware (B5).
SESSION_COOKIE_AGE = 24 * 60 * 60

# --- CSRF (§ 4.1) ----------------------------------------------------------------------
CSRF_COOKIE_NAME = "alpha_csrf"
CSRF_COOKIE_HTTPONLY = False  # lu par le frontend pour l'en-tête X-CSRFToken
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
CSRF_FAILURE_VIEW = "alpha.core.erreurs.vue_echec_csrf"

# URL publique du frontend (liens des e-mails ; origine de confiance pour le CSRF).
ALPHA_URL_FRONTEND = env("ALPHA_URL_FRONTEND", default="http://localhost:3000").rstrip("/")
CSRF_TRUSTED_ORIGINS = [ALPHA_URL_FRONTEND]

# --- En-têtes de sécurité ------------------------------------------------------------
# HSTS, CSP et redirection HTTPS sont aussi posés par Caddy en recette/prod (D3).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Nombre de proxys de confiance devant Django (Caddy en recette/prod, Next.js en
# dev) : sert à lire l'IP réelle dans X-Forwarded-For (RequestIdMiddleware).
ALPHA_NB_PROXIES_CONFIANCE = env.int("ALPHA_NB_PROXIES_CONFIANCE", default=1)

# --- Comptes (§ 2.2, tâche B3) ---------------------------------------------------------
# Utilisateur ALPHA : e-mail (citext) unique sur toute la plateforme (P1), UUID,
# sans PermissionsMixin (auth.Group / auth.Permission ne sont pas utilisés, § 1.1).
AUTH_USER_MODEL = "comptes.Utilisateur"

# --- Mots de passe (§ 4.9) ----------------------------------------------------------
# Argon2id uniquement : aucun autre hacheur n'est accepté.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
# Validateurs standards ; les règles propres à ALPHA (3 catégories sur 4,
# historique, années de naissance) sont ajoutées avec le modèle Utilisateur (B3/B5).
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("prenom", "nom", "email")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Secrets applicatifs (§ 4.4, § 4.9) ------------------------------------------------
# Clés MultiFernet : la première chiffre, toutes déchiffrent.
ALPHA_CLES_CHIFFREMENT = env.list("ALPHA_CLES_CHIFFREMENT")
# Poivre HMAC-SHA256 des codes de secours et des clés de limitation de débit.
ALPHA_HMAC_POIVRE = env("ALPHA_HMAC_POIVRE")

# --- Internationalisation (§ 2.1, P10) --------------------------------------------------
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français")]
USE_I18N = True
TIME_ZONE = "Africa/Dakar"
USE_TZ = True

# --- E-mails (envoi via Celery, B6) -------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="ALPHA <no-reply@alpha.localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- Journal d'audit (§ 6, décision P7) ------------------------------------------------------
# Adresse sécurité FYXOP (réglage de plateforme) : ancre quotidienne de toutes les
# chaînes et alerte immédiate en cas de rupture. Vide : aucun envoi vers FYXOP.
ALPHA_EMAIL_SECURITE_FYXOP = env("ALPHA_EMAIL_SECURITE_FYXOP", default="")
# Points de raccordement (B3) : chemins pointés, None tant que Utilisateur n'existe pas.
#   uuid -> alpha.audit.services.Acteur | None   (libellé figé de l'acteur courant)
ALPHA_AUDIT_RESOLVEUR_ACTEUR = None
#   etablissement_id -> list[str]                (titulaires de audit.lecture, alerte de rupture)
ALPHA_AUDIT_DESTINATAIRES_AUDIT_LECTURE = None

# --- Django REST framework (§ 5) ----------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Fermé par défaut : chaque vue déclare ses permissions (alpha.core.permissions).
    "DEFAULT_PERMISSION_CLASSES": ["alpha.core.permissions.RefuserTout"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "alpha.core.pagination.PaginationPage",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "alpha.core.erreurs.gestionnaire_exceptions",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "DATETIME_FORMAT": "iso-8601",
    "COERCE_DECIMAL_TO_STRING": True,
}

# --- drf-spectacular (§ 5, § 7.4) -------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "ALPHA — API",
    "DESCRIPTION": (
        "API REST v1 d'ALPHA, workflow décisionnel multi-établissements. "
        "Authentification par cookie de session (alpha_sid) ; toute méthode non sûre "
        "exige l'en-tête X-CSRFToken (cookie alpha_csrf). "
        "Erreurs : {code, message, details}."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    # Schémas distincts en lecture et en écriture (types plus précis pour openapi-typescript).
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SERVE_AUTHENTICATION": [],
    # Noms explicites des énumérations homonymes (champs « statut », B8).
    "ENUM_NAME_OVERRIDES": {
        "StatutAbsenceEnum": "alpha.delegations.models.StatutAbsence",
        "StatutDelegationEnum": "alpha.delegations.models.StatutDelegation",
    },
}
# Schéma OpenAPI (/api/v1/schema/) et documentation interactive (/api/v1/docs/) :
# montés seulement si ALPHA_DOC_API_ACTIVE (dev, test, recette ; jamais en production).
# ALPHA_DOC_API_RESERVEE_CONNECTES : en recette, réservés aux utilisateurs connectés
# (décision du client) ; en dev et en test, ouverts (génération des types du frontend).
ALPHA_DOC_API_ACTIVE = False
ALPHA_DOC_API_RESERVEE_CONNECTES = False

# --- Celery (§ 3.7, § 6.5) -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# Pas de backend de résultats : les tâches ALPHA ne renvoient rien d'utile.
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 10 * 60
# Files : « defaut » (décorateur tache_tenant, § 3.7) et « celery » (file par défaut).
CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_QUEUES = (
    Queue("defaut", routing_key="defaut"),
    Queue("celery", routing_key="celery"),
)
CELERY_TASK_CREATE_MISSING_QUEUES = False
# Planification (§ 6.5, heure de Dakar) : complétée par les tâches B5, B8 et B9.
CELERY_BEAT_SCHEDULE: dict = {
    # B4 : contrôle d'intégrité de toutes les chaînes d'audit (une sous-tâche par chaîne).
    "audit-verifier-toutes-chaines": {
        "task": "audit.verifier_toutes_chaines",
        "schedule": crontab(hour=2, minute=0),
    },
    # B4 : ancre quotidienne (dernier seq/hash) au contrôle interne et à FYXOP (P7).
    "audit-envoyer-ancres": {
        "task": "audit.envoyer_ancres",
        "schedule": crontab(hour=2, minute=30),
    },
    # B8 : entrée en vigueur et clôture des délégations à leurs dates (idempotentes).
    "delegations-activer": {
        "task": "delegations.activer_delegations",
        "schedule": crontab(minute="*/5"),
    },
    "delegations-cloturer": {
        "task": "delegations.cloturer_delegations",
        "schedule": crontab(minute="*/5"),
    },
}

# --- Journaux ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"contexte": {"()": "alpha.core.journalisation.FiltreContexte"}},
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s : %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["contexte"],
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": env("ALPHA_NIVEAU_JOURNAL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
