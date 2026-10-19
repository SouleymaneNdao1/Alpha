"""Routes ``/api/v1/plateforme/`` : console FYXOP (§ 5.7, tâche B10)."""

from django.urls import path

from . import vues as v

urlpatterns = [
    path("etablissements", v.EtablissementsVue.as_view(), name="plateforme-etablissements"),
    path(
        "etablissements/<uuid:etablissement_id>",
        v.EtablissementVue.as_view(),
        name="plateforme-etablissement",
    ),
    path(
        "etablissements/<uuid:etablissement_id>/administrateurs",
        v.AdministrateursVue.as_view(),
        name="plateforme-administrateurs",
    ),
    path(
        "etablissements/<uuid:etablissement_id>/reinitialisation-authenticator",
        v.ReinitialisationAuthenticatorVue.as_view(),
        name="plateforme-reinitialisation-authenticator",
    ),
    path("audit", v.AuditPlateformeVue.as_view(), name="plateforme-audit"),
    path("moi", v.MoiPlateformeVue.as_view(), name="plateforme-moi"),
]
