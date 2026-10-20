"""Routes d'administration des absences et délégations, montées sous ``/api/v1/admin/`` (B13)."""

from django.urls import path

from . import vues_admin as v

urlpatterns = [
    path("absences", v.AbsencesAdminVue.as_view(), name="admin-absences"),
    path("absences/candidats", v.CandidatsAdminVue.as_view(), name="admin-absences-candidats"),
    path("delegations", v.DelegationsAdminVue.as_view(), name="admin-delegations"),
    path(
        "delegations/<uuid:delegation_id>/revoquer",
        v.RevoquerDelegationAdminVue.as_view(),
        name="admin-delegation-revoquer",
    ),
]
