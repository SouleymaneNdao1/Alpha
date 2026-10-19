"""Routes des absences et délégations, montées sous ``/api/v1/`` (§ 5.3, § 5.4)."""

from django.urls import path

from . import vues

urlpatterns = [
    path("moi/absences/", vues.MesAbsencesVue.as_view(), name="moi-absences"),
    path(
        "moi/absences/<uuid:absence_id>/annuler/",
        vues.AnnulerMonAbsenceVue.as_view(),
        name="moi-absence-annuler",
    ),
    path(
        "moi/delegataires-possibles/",
        vues.DelegatairesPossiblesVue.as_view(),
        name="moi-delegataires-possibles",
    ),
    path(
        "moi/delegations-recues/",
        vues.DelegationsRecuesVue.as_view(),
        name="moi-delegations-recues",
    ),
    path("absences/<uuid:absence_id>/", vues.AbsenceVue.as_view(), name="absence"),
    path(
        "absences/<uuid:absence_id>/valider/",
        vues.ValiderAbsenceVue.as_view(),
        name="absence-valider",
    ),
    path(
        "absences/<uuid:absence_id>/refuser/",
        vues.RefuserAbsenceVue.as_view(),
        name="absence-refuser",
    ),
]
