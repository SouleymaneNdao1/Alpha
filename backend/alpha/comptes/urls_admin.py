"""Routes ``/api/v1/admin/`` des comptes (§ 5.5, tâche B7)."""

from django.urls import path

from . import vues_admin as v

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
]
