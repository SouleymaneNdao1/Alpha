"""Routes ``/api/v1/audit/`` (§ 5.6, tâche B11)."""

from django.urls import path

from . import vues as v

urlpatterns = [
    path("evenements", v.EvenementsVue.as_view(), name="audit-evenements"),
    path("indicateurs", v.IndicateursVue.as_view(), name="audit-indicateurs"),
    path("export.xlsx", v.ExportVue.as_view(), name="audit-export"),
    path("controles", v.ControlesVue.as_view(), name="audit-controles"),
]
