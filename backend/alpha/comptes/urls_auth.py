"""Routes ``/api/v1/auth/`` (§ 5.2) : B5 (connexion) et B6 (activation, réenrôlement,
mot de passe oublié, téléphone perdu)."""

from django.urls import path

from . import vues_auth
from . import vues_parcours as p

app_name = "auth"

urlpatterns = [
    path("csrf", vues_auth.VueCsrf.as_view(), name="csrf"),
    path("session", vues_auth.VueSession.as_view(), name="session"),
    path("connexion", vues_auth.VueConnexion.as_view(), name="connexion"),
    path("mfa", vues_auth.VueMfa.as_view(), name="mfa"),
    path("deconnexion", vues_auth.VueDeconnexion.as_view(), name="deconnexion"),
    # B6 : activation (§ 4.3) et réenrôlement (§ 4.5)
    path("activation/<str:jeton>", p.VueActivationInfos.as_view(), name="activation"),
    path(
        "activation/<str:jeton>/mot-de-passe",
        p.VueActivationMotDePasse.as_view(),
        name="activation-mot-de-passe",
    ),
    path(
        "activation/<str:jeton>/authenticator",
        p.VueActivationAuthenticator.as_view(),
        name="activation-authenticator",
    ),
    path(
        "activation/<str:jeton>/authenticator/confirmer",
        p.VueActivationConfirmer.as_view(),
        name="activation-authenticator-confirmer",
    ),
    path(
        "activation/<str:jeton>/terminer",
        p.VueActivationTerminer.as_view(),
        name="activation-terminer",
    ),
    path("reenrolement/<str:jeton>", p.VueReenrolementInfos.as_view(), name="reenrolement"),
    path(
        "reenrolement/<str:jeton>/mot-de-passe",
        p.VueReenrolementMotDePasse.as_view(),
        name="reenrolement-mot-de-passe",
    ),
    path(
        "reenrolement/<str:jeton>/authenticator",
        p.VueReenrolementAuthenticator.as_view(),
        name="reenrolement-authenticator",
    ),
    path(
        "reenrolement/<str:jeton>/authenticator/confirmer",
        p.VueReenrolementConfirmer.as_view(),
        name="reenrolement-authenticator-confirmer",
    ),
    path(
        "reenrolement/<str:jeton>/terminer",
        p.VueReenrolementTerminer.as_view(),
        name="reenrolement-terminer",
    ),
    # B6 : mot de passe oublié (§ 4.7) et téléphone perdu (§ 4.5)
    path("mot-de-passe/oubli", p.VueOubli.as_view(), name="mot-de-passe-oubli"),
    path(
        "mot-de-passe/reinitialisation/<str:jeton>",
        p.VueReinitialisation.as_view(),
        name="mot-de-passe-reinitialisation",
    ),
    path("telephone-perdu", p.VueTelephonePerdu.as_view(), name="telephone-perdu"),
]
