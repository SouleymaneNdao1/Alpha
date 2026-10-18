"""Routes de l'API (architecture § 5).

Base : /api/v1. Schéma OpenAPI : /api/v1/schema/ ; documentation interactive
(Swagger) : /api/v1/docs/ ; ouverts en dev, réservés aux utilisateurs connectés en
recette, non routés en production (``alpha.core.documentation_api``).
Sonde de santé publique : /api/v1/sante/ (``alpha.core.sante``).

Les routes métier sont ajoutées par les tâches suivantes :
    /api/v1/auth/...        alpha.comptes (B5, B6)
    /api/v1/moi/...         alpha.comptes, alpha.notifications (B9)
    /api/v1/taches/...      alpha.taches, alpha.delegations (B8)
    /api/v1/admin/...       alpha.comptes, alpha.organisation (B7)
    /api/v1/audit/...       alpha.audit (B11)
    /api/v1/plateforme/...  alpha.plateforme (B10)
"""

from django.conf import settings
from django.urls import include, path

from alpha.core.documentation_api import routes_documentation
from alpha.core.sante import sante

urlpatterns = [
    path("api/v1/sante/", sante, name="sante"),
    # À traiter, absences et délégations (§ 5.3, § 5.4, B8).
    path("api/v1/", include("alpha.taches.urls")),
    path("api/v1/", include("alpha.delegations.urls")),
]

urlpatterns += routes_documentation(
    active=settings.ALPHA_DOC_API_ACTIVE,
    reservee_connectes=settings.ALPHA_DOC_API_RESERVEE_CONNECTES,
)

# Réponses d'erreur au format {code, message, details} hors DRF (DEBUG=False).
handler400 = "alpha.core.erreurs.vue_400"
handler403 = "alpha.core.erreurs.vue_403"
handler404 = "alpha.core.erreurs.vue_404"
handler500 = "alpha.core.erreurs.vue_500"
