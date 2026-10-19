"""Routes ``/api/v1/admin/`` des comptes (§ 5.5, tâches B7 et B6 pour les signalements)."""

from django.urls import path

from . import vues_admin as v
from . import vues_signalements as sig

urlpatterns = [
    path("utilisateurs", v.UtilisateursVue.as_view(), name="admin-utilisateurs"),
    # Avant « utilisateurs/<uuid> » : « historique » n'est pas un identifiant.
    path(
        "utilisateurs/historique", v.HistoriqueVue.as_view(), name="admin-utilisateurs-historique"
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>", v.UtilisateurVue.as_view(), name="admin-utilisateur"
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/affectations",
        v.AffectationsUtilisateurVue.as_view(),
        name="admin-utilisateur-affectations",
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/suspendre",
        v.SuspendreVue.as_view(),
        name="admin-utilisateur-suspendre",
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/reactiver",
        v.ReactiverVue.as_view(),
        name="admin-utilisateur-reactiver",
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/deverrouiller",
        v.DeverrouillerVue.as_view(),
        name="admin-utilisateur-deverrouiller",
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/renvoyer-invitation",
        v.RenvoyerInvitationVue.as_view(),
        name="admin-utilisateur-renvoyer-invitation",
    ),
    path(
        "utilisateurs/<uuid:utilisateur_id>/sessions/revoquer",
        v.RevoquerSessionsVue.as_view(),
        name="admin-utilisateur-revoquer-sessions",
    ),
    path(
        "affectations/<uuid:affectation_id>/terminer",
        v.TerminerAffectationVue.as_view(),
        name="admin-affectation-terminer",
    ),
    # Téléphone perdu (§ 4.5, B6)
    path("signalements-telephone", sig.SignalementsVue.as_view(), name="admin-signalements"),
    path(
        "signalements-telephone/<uuid:signalement_id>/reinitialiser",
        sig.ReinitialiserSignalementVue.as_view(),
        name="admin-signalement-reinitialiser",
    ),
    path(
        "signalements-telephone/<uuid:signalement_id>/annuler",
        sig.AnnulerSignalementVue.as_view(),
        name="admin-signalement-annuler",
    ),
]
