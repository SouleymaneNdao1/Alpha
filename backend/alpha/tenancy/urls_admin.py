"""Routes ``/api/v1/admin/`` des paramètres de l'établissement (§ 5.5, tâche B7)."""

from django.urls import path

from .parametres import ParametresSecuriteVue

urlpatterns = [
    path("parametres-securite", ParametresSecuriteVue.as_view(), name="admin-parametres-securite"),
]
