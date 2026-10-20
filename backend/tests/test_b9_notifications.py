"""Préférences et notifications in-app (§ 5.3, § 5.4 ; tâche B9)."""

from __future__ import annotations

import uuid

import pytest
from freezegun import freeze_time

from alpha.audit.models import EvenementAudit
from alpha.notifications.models import Notification, PreferencesNotification
from alpha.notifications.services import notifier
from alpha.taches import services as taches
from alpha.taches.models import Action, Module
from alpha.tenancy.contexte import contexte_tenant
from tests.fabriques import UtilisateurFactory
from tests.outils_b8 import organisation_b8

pytestmark = pytest.mark.django_db

T0 = "2030-03-04T08:00:00+00:00"
DEBUT = "2030-03-11T00:00:00+00:00"
FIN = "2030-03-16T00:00:00+00:00"


@pytest.fixture
def horloge():
    with freeze_time(T0) as h:
        yield h


@pytest.fixture
def org(etab_a, horloge):
    return organisation_b8(etab_a)


def _types(org, utilisateur) -> list[str]:
    with contexte_tenant(org.etab.id):
        return list(
            Notification.objects.filter(utilisateur=utilisateur)
            .order_by("cree_le", "type")
            .values_list("type", flat=True)
        )


# --- Préférences ------------------------------------------------------------------------------


def test_preferences_par_defaut_et_modification(etab_a, client_connecte):
    u = UtilisateurFactory(etablissement=etab_a)
    client = client_connecte(u)
    r = client.get("/api/v1/moi/preferences-notification")
    assert r.status_code == 200
    assert r.json() == {
        "email": True,
        "push": False,
        "sms": False,
        "resume_quotidien": False,
        "heure_resume": "07:30",
    }
    corps = {
        "email": True,
        "push": True,
        "sms": True,
        "resume_quotidien": True,
        "heure_resume": "18:15",
    }
    r = client.put("/api/v1/moi/preferences-notification", corps, format="json")
    assert r.status_code == 200 and r.json() == corps
    assert (
        client.put(
            "/api/v1/moi/preferences-notification", {"email": False}, format="json"
        ).status_code
        == 400
    )
    with contexte_tenant(etab_a.id):
        evt = EvenementAudit.objects.get(action="notifications.preferences.modifiees")
    assert evt.apres == {
        "push": True,
        "sms": True,
        "resume_quotidien": True,
        "heure_resume": "18:15:00",
    }


def test_invitation_cree_les_preferences(client_admin, banque):
    from alpha.organisation.models import Role

    with contexte_tenant(banque.id):
        role = Role.objects.filter(actif=True).first()
    r = client_admin.post(
        "/api/v1/admin/utilisateurs",
        {
            "email": "nouveau@banque.test",
            "prenom": "Moussa",
            "nom": "Fall",
            "role_id": str(role.id),
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    with contexte_tenant(banque.id):
        assert PreferencesNotification.objects.filter(utilisateur_id=r.json()["id"]).exists()


# --- Notifications ----------------------------------------------------------------------------


def test_liste_lecture_et_isolation(etab_a, etab_b, client_connecte):
    u = UtilisateurFactory(etablissement=etab_a)
    v = UtilisateurFactory(etablissement=etab_a)
    w = UtilisateurFactory(etablissement=etab_b)
    with contexte_tenant(etab_a.id):
        (n1,) = notifier([u], type="TACHE_NOUVELLE", titre="Un")
        notifier([u], type="TACHE_NOUVELLE", titre="Deux")
        (n_v,) = notifier([v], type="TACHE_NOUVELLE", titre="Pour V")
    with contexte_tenant(etab_b.id):
        (n_w,) = notifier([w], type="TACHE_NOUVELLE", titre="Pour W")
    client = client_connecte(u)
    r = client.get("/api/v1/moi/notifications")
    assert r.status_code == 200
    assert r.json()["count"] == 2 and r.json()["non_lues"] == 2
    assert {n["titre"] for n in r.json()["results"]} == {"Un", "Deux"}
    assert client.post(f"/api/v1/moi/notifications/{n1.id}/lue").status_code == 204
    r = client.get("/api/v1/moi/notifications?non_lues=1")
    assert r.json()["count"] == 1 and r.json()["non_lues"] == 1
    # Autre utilisateur, autre établissement, inexistante : 404.
    for autre in (n_v.id, n_w.id, uuid.uuid4()):
        assert client.post(f"/api/v1/moi/notifications/{autre}/lue").status_code == 404
    assert client.post("/api/v1/moi/notifications/tout-lu").status_code == 204
    assert client.get("/api/v1/moi/notifications").json()["non_lues"] == 0
    assert client_connecte(v).get("/api/v1/moi/notifications").json()["non_lues"] == 1


def test_parcours_absence_notifie_demandeur_et_delegataire(org, horloge, client_connecte):
    corps = {"debut": DEBUT, "fin": FIN, "motif": "CONGE", "delegataire_id": str(org.cheikh.pk)}
    r = client_connecte(org.awa).post("/api/v1/moi/absences", corps, format="json")
    assert r.status_code == 201, r.content
    absence_id = r.json()["id"]
    assert _types(org, org.mamadou) == ["TACHE_NOUVELLE"]  # le valideur, par sa tâche
    assert _types(org, org.cheikh) == ["DELEGATION_PROPOSEE"]

    r = client_connecte(org.mamadou).post(
        f"/api/v1/absences/{absence_id}/valider", {}, format="json"
    )
    assert r.status_code == 200, r.content
    assert _types(org, org.awa) == ["ABSENCE_VALIDEE"]
    assert _types(org, org.cheikh) == ["DELEGATION_PROPOSEE", "DELEGATION_RECUE"]

    # Entrée en vigueur par la tâche planifiée, puis fin.
    from alpha.delegations import tasks

    horloge.move_to("2030-03-11T00:10:00+00:00")
    assert tasks.activer_delegations_etablissement.delay(str(org.etab.id)).get() == 1
    horloge.move_to("2030-03-16T00:10:00+00:00")
    assert tasks.cloturer_delegations_etablissement.delay(str(org.etab.id)).get() == 1
    assert _types(org, org.cheikh)[-2:] == ["DELEGATION_ACTIVE", "DELEGATION_TERMINEE"]


def test_validation_pendant_l_absence_sans_doublon(org, horloge, client_connecte):
    horloge.move_to("2030-03-12T08:00:00+00:00")
    corps = {
        "debut": "2030-03-12T09:00:00+00:00",
        "fin": FIN,
        "motif": "CONGE",
        "delegataire_id": str(org.cheikh.pk),
    }
    absence_id = (
        client_connecte(org.awa).post("/api/v1/moi/absences", corps, format="json").json()["id"]
    )
    horloge.move_to("2030-03-12T10:00:00+00:00")
    r = client_connecte(org.mamadou).post(
        f"/api/v1/absences/{absence_id}/valider", {}, format="json"
    )
    assert r.status_code == 200, r.content
    assert _types(org, org.cheikh) == ["DELEGATION_PROPOSEE", "DELEGATION_RECUE"]


def test_refus_notifie_le_demandeur(org, horloge, client_connecte):
    corps = {"debut": DEBUT, "fin": FIN, "motif": "CONGE", "delegataire_id": str(org.cheikh.pk)}
    absence_id = (
        client_connecte(org.awa).post("/api/v1/moi/absences", corps, format="json").json()["id"]
    )
    r = client_connecte(org.mamadou).post(
        f"/api/v1/absences/{absence_id}/refuser", {"motif": "Clôture"}, format="json"
    )
    assert r.status_code == 200
    assert _types(org, org.awa) == ["ABSENCE_REFUSEE"]
    # Horloge figée : même cree_le, tri par type.
    assert _types(org, org.cheikh) == ["DELEGATION_ANNULEE", "DELEGATION_PROPOSEE"]


def test_tache_de_role_notifie_les_titulaires_du_perimetre(org):
    with contexte_tenant(org.etab.id):
        taches.ouvrir(
            ("tests.dossier", uuid.uuid4()),
            module=Module.CREDIT,
            action=Action.DECIDER,
            titre="Dossier agence",
            assigne_role=org.analyste,
            assigne_unite=org.agence,
            demandeur=org.cheikh,
        )
    # Awa (agence) et Mamadou (direction, parent) ; Cheikh est le demandeur ; Fatou sans rôle.
    assert _types(org, org.awa) == ["TACHE_NOUVELLE"]
    assert _types(org, org.mamadou) == ["TACHE_NOUVELLE"]
    assert _types(org, org.cheikh) == [] and _types(org, org.fatou) == []
