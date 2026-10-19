"""Routes « À traiter » (§ 5.4), montées sous ``/api/v1/``."""

from django.urls import path

from . import vues

urlpatterns = [
    path("taches/", vues.TachesVue.as_view(), name="taches"),
    path("taches/compteurs/", vues.TachesCompteursVue.as_view(), name="taches-compteurs"),
    path("taches/<uuid:tache_id>/", vues.TacheVue.as_view(), name="tache"),
]
