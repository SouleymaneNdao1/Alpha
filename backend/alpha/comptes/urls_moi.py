"""Routes ``/api/v1/moi`` de « Mon compte » (§ 5.3, tâche B9), montées sous ``/api/v1/``.

Les absences et délégations (``/moi/absences``…) relèvent de B8
(``alpha.delegations.urls``) ; préférences et notifications : ``alpha.notifications.urls``.
"""

from django.urls import path

from . import vues_moi as v

urlpatterns = [
    path("moi", v.MoiVue.as_view(), name="moi"),
    path("moi/mot-de-passe", v.MotDePasseVue.as_view(), name="moi-mot-de-passe"),
    path("moi/securite", v.SecuriteVue.as_view(), name="moi-securite"),
    path(
        "moi/authenticator/changement",
        v.ChangementAuthenticatorVue.as_view(),
        name="moi-authenticator-changement",
    ),
    path(
        "moi/authenticator/changement/confirmer",
        v.ConfirmerChangementAuthenticatorVue.as_view(),
        name="moi-authenticator-changement-confirmer",
    ),
    path("moi/codes-secours", v.CodesSecoursVue.as_view(), name="moi-codes-secours"),
    path("moi/telephone-perdu", v.TelephonePerduVue.as_view(), name="moi-telephone-perdu"),
    path("moi/sessions", v.SessionsVue.as_view(), name="moi-sessions"),
    # Avant « <uuid> » (l'uuid est typé, mais l'ordre reste explicite).
    path(
        "moi/sessions/revoquer-autres",
        v.RevoquerAutresSessionsVue.as_view(),
        name="moi-sessions-revoquer-autres",
    ),
    path("moi/sessions/<uuid:session_id>", v.SessionVue.as_view(), name="moi-session"),
]
