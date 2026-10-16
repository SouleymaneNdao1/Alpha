"""Routes de l'API (architecture § 5).

Base : /api/v1. Schéma OpenAPI : /api/v1/schema/ ; documentation interactive
(Swagger) : /api/v1/docs/, en dev et en recette uniquement (ALPHA_DOC_API_ACTIVE).

Les routes métier sont ajoutées par les tâches suivantes :
    /api/v1/auth/...        alpha.comptes (B5, B6)
    /api/v1/moi/...         alpha.comptes, alpha.notifications (B9)
    /api/v1/taches/...      alpha.taches, alpha.delegations (B8)
    /api/v1/admin/...       alpha.comptes, alpha.organisation (B7)
    /api/v1/audit/...       alpha.audit (B11)
    /api/v1/plateforme/...  alpha.plateforme (B10)
"""

from django.conf import settings
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
]

if settings.ALPHA_DOC_API_ACTIVE:
    urlpatterns += [
        path(
            "api/v1/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="documentation",
        ),
    ]

# Réponses d'erreur au format {code, message, details} hors DRF (DEBUG=False).
handler400 = "alpha.core.erreurs.vue_400"
handler403 = "alpha.core.erreurs.vue_403"
handler404 = "alpha.core.erreurs.vue_404"
handler500 = "alpha.core.erreurs.vue_500"
