"""Routes ``/api/v1/auth/`` livrées par B5 (§ 5.2) ; B6 ajoute activation, réenrôlement,
mot de passe oublié et téléphone perdu."""

from django.urls import path

from . import vues_auth

app_name = "auth"

urlpatterns = [
    path("csrf", vues_auth.VueCsrf.as_view(), name="csrf"),
    path("session", vues_auth.VueSession.as_view(), name="session"),
    path("connexion", vues_auth.VueConnexion.as_view(), name="connexion"),
    path("mfa", vues_auth.VueMfa.as_view(), name="mfa"),
    path("deconnexion", vues_auth.VueDeconnexion.as_view(), name="deconnexion"),
]
