"""Administration des absences et délégations (tâche B13, § 5.5, décision P5).

Routes : ``/admin/absences`` (liste, création pour le compte d'un utilisateur),
``/admin/absences/candidats``, ``/admin/delegations`` (liste) et
``/admin/delegations/{id}/revoquer``. Contrôles : permissions fermées par défaut,
super-admin refusé, isolation entre établissements (RLS), règles P5 réutilisées,
journalisation.
"""

from __future__ import annotations

import uuid

import pytest
from freezegun import freeze_time

from alpha.audit.models import EvenementAudit
from alpha.delegations.models import Absence, Delegation, StatutDelegation
from alpha.organisation.codes_permission import CodePermission as C
from alpha.taches import services as taches
from alpha.taches.models import Action, Module
from alpha.taches.visibilite import visibles_pour
from alpha.tenancy.contexte import contexte_tenant
from tests.fabriques import UtilisateurFactory
from tests.outils_admin import avec_permissions
from tests.outils_b8 import organisation_b8

pytestmark = pytest.mark.django_db

API = "/api/v1/admin"
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


@pytest.fixture
def org_b(etab_b, horloge):
    return organisation_b8(etab_b)


def _corps(absent, delegataire, **champs):
    corps = {
        "utilisateur_id": str(absent.pk),
        "debut": DEBUT,
        "fin": FIN,
        "motif": "CONGE",
        "delegataire_id": str(delegataire.pk),
    }
    corps.update(champs)
    return corps


def _absence_validee(org, client_connecte, absent=None, delegataire=None):
    """Absence (Awa → Cheikh par défaut) déclarée et validée par l'admin."""
    reponse = client_connecte(org.admin).post(
        f"{API}/absences",
        _corps(absent or org.awa, delegataire or org.cheikh, valider=True),
        format="json",
    )
    assert reponse.status_code == 201, reponse.json()
    return reponse.json()


def _evenements(etab, action):
    with contexte_tenant(etab.id):
        return list(EvenementAudit.objects.filter(action=action).order_by("seq"))


# --- Permissions ---------------------------------------------------------------------------------

ROUTES = [
    ("get", "/absences"),
    ("post", "/absences"),
    ("get", "/absences/candidats"),
    ("get", "/delegations"),
    ("post", f"/delegations/{uuid.uuid4()}/revoquer"),
]


@pytest.mark.parametrize(("methode", "chemin"), ROUTES)
def test_anonyme_401(client_api, methode, chemin):
    assert getattr(client_api, methode)(f"{API}{chemin}", {}, format="json").status_code == 401


@pytest.mark.parametrize(("methode", "chemin"), ROUTES)
def test_non_admin_403(org, client_connecte, methode, chemin):
    reponse = getattr(client_connecte(org.cheikh), methode)(f"{API}{chemin}", {}, format="json")
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "PERMISSION_REFUSEE"


@pytest.mark.parametrize(("methode", "chemin"), ROUTES)
def test_super_admin_fyxop_403(client_connecte, methode, chemin):
    client = client_connecte(UtilisateurFactory(super_admin=True))
    assert getattr(client, methode)(f"{API}{chemin}", {}, format="json").status_code == 403


def test_admin_utilisateurs_lit_les_delegations_seulement(org, client_connecte):
    client = client_connecte(avec_permissions(org.etab, C.ADMIN_UTILISATEURS))
    assert client.get(f"{API}/delegations").status_code == 200
    assert client.get(f"{API}/absences").status_code == 403
    assert client.post(f"{API}/absences", {}, format="json").status_code == 403
    delegation_id = uuid.uuid4()
    reponse = client.post(
        f"{API}/delegations/{delegation_id}/revoquer", {"motif": "x"}, format="json"
    )
    assert reponse.status_code == 403


# --- Listes et filtres ---------------------------------------------------------------------------


def test_liste_des_absences_et_filtres(org, client_connecte):
    client_connecte(org.awa).post(
        "/api/v1/moi/absences",
        {"debut": DEBUT, "fin": FIN, "motif": "CONGE", "delegataire_id": str(org.cheikh.pk)},
        format="json",
    )
    client = client_connecte(org.admin)
    page = client.get(f"{API}/absences").json()
    assert page["count"] == 1
    ligne = page["results"][0]
    assert ligne["demandeur"]["nom"] == "Awa Diop"
    assert ligne["statut"] == "SOUMISE"
    assert ligne["delegation"]["delegataire"]["nom"] == "Cheikh Badiane"
    assert ligne["peut_decider"] is True

    assert client.get(f"{API}/absences?statut=VALIDEE").json()["count"] == 0
    assert client.get(f"{API}/absences?utilisateur_id={org.cheikh.pk}").json()["count"] == 0
    assert client.get(f"{API}/absences?du=2030-03-15&au=2030-03-20").json()["count"] == 1
    assert client.get(f"{API}/absences?du=2030-03-16").json()["count"] == 0
    assert client.get(f"{API}/absences?au=2030-03-10").json()["count"] == 0

    reponse = client.get(f"{API}/absences?statut=X")
    assert reponse.status_code == 400
    assert reponse.json()["code"] == "VALIDATION"
    assert "statut" in reponse.json()["details"]
    assert client.get(f"{API}/absences?du=2030-03-20&au=2030-03-10").status_code == 400


def test_liste_des_delegations_et_filtres(org, client_connecte):
    _absence_validee(org, client_connecte)
    client = client_connecte(org.admin)
    page = client.get(f"{API}/delegations").json()
    assert page["count"] == 1
    ligne = page["results"][0]
    assert (ligne["delegant"]["nom"], ligne["delegataire"]["nom"]) == ("Awa Diop", "Cheikh Badiane")
    assert (ligne["statut"], ligne["effective"], ligne["origine"]) == ("ACTIVE", False, "ABSENCE")
    assert client.get(f"{API}/delegations?statut=TERMINEE").json()["count"] == 0
    # utilisateur_id : délégant OU délégataire.
    assert client.get(f"{API}/delegations?utilisateur_id={org.cheikh.pk}").json()["count"] == 1
    assert client.get(f"{API}/delegations?utilisateur_id={org.fatou.pk}").json()["count"] == 0
    assert client.get(f"{API}/delegations?statut=X").status_code == 400


def test_candidats_avec_controle_p5(org, client_connecte):
    client = client_connecte(org.admin)
    reponse = client.get(f"{API}/absences/candidats?pour={org.awa.pk}")
    assert reponse.status_code == 200
    candidats = {c["nom"]: c["pouvoirs_suffisants"] for c in reponse.json()}
    assert "Awa Diop" not in candidats
    assert candidats["Cheikh Badiane"] is True
    assert candidats["Fatou Ndiaye"] is False
    # Sans « pour » : tous les actifs, sans contrôle.
    tous = client.get(f"{API}/absences/candidats?q=diop").json()
    assert [(c["nom"], c["pouvoirs_suffisants"]) for c in tous] == [("Awa Diop", None)]
    assert client.get(f"{API}/absences/candidats?pour=pas-un-uuid").status_code == 400


# --- Création pour le compte d'un utilisateur (services existants) -------------------------------


def test_creation_pour_le_compte_d_un_utilisateur(org, client_connecte):
    reponse = client_connecte(org.admin).post(
        f"{API}/absences", _corps(org.awa, org.cheikh, commentaire="Saisie RH"), format="json"
    )
    assert reponse.status_code == 201, reponse.json()
    absence = reponse.json()
    assert absence["demandeur"]["id"] == str(org.awa.pk)
    assert absence["statut"] == "SOUMISE"
    assert absence["valideur"]["id"] == str(org.mamadou.pk)  # P5 : le responsable
    assert absence["delegation"]["statut"] == "EN_ATTENTE"
    # Le responsable reçoit la tâche de validation, comme pour une déclaration directe.
    taches = client_connecte(org.mamadou).get("/api/v1/taches").json()["results"]
    assert [t["lien"] for t in taches] == [f"/absences/{absence['id']}"]
    # Journal : l'auteur est l'administrateur.
    (evenement,) = _evenements(org.etab, "absence.soumise")
    assert evenement.acteur_id == org.admin.pk
    assert "pour le compte" in evenement.detail


def test_creation_avec_validation_immediate(org, client_connecte):
    absence = _absence_validee(org, client_connecte)
    assert absence["statut"] == "VALIDEE"
    assert absence["delegation"]["statut"] == "ACTIVE"
    assert [e.acteur_id for e in _evenements(org.etab, "absence.validee")] == [org.admin.pk]


def test_creation_respecte_p5(org, client_connecte):
    client = client_connecte(org.admin)
    # Pouvoirs insuffisants : même contrôle que /moi/absences.
    reponse = client.post(f"{API}/absences", _corps(org.awa, org.fatou), format="json")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "POUVOIRS_INSUFFISANTS"
    # Pas de sous-délégation : Cheikh, délégataire d'Awa, ne peut pas redéléguer.
    _absence_validee(org, client_connecte)
    reponse = client.post(
        f"{API}/absences",
        _corps(org.cheikh, org.mamadou, debut="2030-03-13T00:00:00Z"),
        format="json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "SOUS_DELEGATION_INTERDITE"
    # Délégation bornée : la fin doit suivre le début.
    reponse = client.post(
        f"{API}/absences", _corps(org.mamadou, org.cheikh, fin=DEBUT), format="json"
    )
    assert reponse.status_code == 400


def test_creation_refusee_pour_soi_ou_inconnu(org, client_connecte):
    client = client_connecte(org.admin)
    reponse = client.post(f"{API}/absences", _corps(org.admin, org.cheikh), format="json")
    assert reponse.status_code == 400
    assert "utilisateur_id" in reponse.json()["details"]
    corps = _corps(org.awa, org.cheikh, utilisateur_id=str(uuid.uuid4()))
    assert client.post(f"{API}/absences", corps, format="json").status_code == 400


# --- Révocation ----------------------------------------------------------------------------------


def test_revocation_pendant_l_absence(org, horloge, client_connecte):
    absence = _absence_validee(org, client_connecte)
    delegation_id = absence["delegation"]["id"]
    with contexte_tenant(org.etab.id):
        tache = taches.ouvrir(
            ("tests.dossier", uuid.uuid4()),
            module=Module.CREDIT,
            action=Action.DECIDER,
            titre="Dossier CR-2030-0412",
            assigne_utilisateur=org.awa,
        )
    horloge.move_to("2030-03-12T09:00:00+00:00")
    with contexte_tenant(org.etab.id):
        assert visibles_pour(org.cheikh).filter(pk=tache.pk).exists()
    client = client_connecte(org.admin)
    url = f"{API}/delegations/{delegation_id}/revoquer"

    reponse = client.post(url, {"motif": " "}, format="json")
    assert reponse.status_code == 400

    reponse = client.post(url, {"motif": "Délégataire muté"}, format="json")
    assert reponse.status_code == 200, reponse.json()
    assert reponse.json()["statut"] == "TERMINEE"
    assert reponse.json()["fin"].startswith("2030-03-12T09:00:00")
    with contexte_tenant(org.etab.id):
        assert Absence.objects.get(pk=absence["id"]).statut == "VALIDEE"  # l'absence demeure
        # Le délégataire ne voit plus les tâches de l'absente.
        assert not visibles_pour(org.cheikh).filter(pk=tache.pk).exists()
    (evenement,) = _evenements(org.etab, "delegation.revoquee")
    assert (evenement.acteur_id, evenement.detail) == (org.admin.pk, "Délégataire muté")
    assert evenement.avant["statut"] == "ACTIVE"
    assert evenement.apres["statut"] == "TERMINEE"

    # Une seconde révocation est refusée.
    reponse = client.post(url, {"motif": "encore"}, format="json")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "STATUT_INVALIDE"


def test_revocation_avant_le_debut_annule(org, client_connecte):
    absence = _absence_validee(org, client_connecte)
    url = f"{API}/delegations/{absence['delegation']['id']}/revoquer"
    reponse = client_connecte(org.admin).post(url, {"motif": "Erreur"}, format="json")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ANNULEE"
    with contexte_tenant(org.etab.id):
        assert Delegation.objects.get(pk=absence["delegation"]["id"]).statut == (
            StatutDelegation.ANNULEE
        )


def test_revocation_d_une_delegation_en_attente_refusee(org, client_connecte):
    reponse = client_connecte(org.admin).post(
        f"{API}/absences", _corps(org.awa, org.cheikh), format="json"
    )
    url = f"{API}/delegations/{reponse.json()['delegation']['id']}/revoquer"
    reponse = client_connecte(org.admin).post(url, {"motif": "x"}, format="json")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "STATUT_INVALIDE"


# --- Isolation entre établissements --------------------------------------------------------------


def test_isolation_entre_etablissements(org, org_b, client_connecte):
    absence_b = _absence_validee(org_b, client_connecte)
    client_a = client_connecte(org.admin)

    assert client_a.get(f"{API}/absences").json()["count"] == 0
    assert client_a.get(f"{API}/delegations").json()["count"] == 0
    # Révoquer une délégation de B : 404, rien ne change.
    url = f"{API}/delegations/{absence_b['delegation']['id']}/revoquer"
    reponse = client_a.post(url, {"motif": "x"}, format="json")
    assert reponse.status_code == 404
    with contexte_tenant(org_b.etab.id):
        delegation = Delegation.objects.get(pk=absence_b["delegation"]["id"])
        assert delegation.statut == StatutDelegation.ACTIVE
    # Déclarer pour un utilisateur de B, ou avec un délégataire de B : refusé.
    reponse = client_a.post(f"{API}/absences", _corps(org_b.awa, org.cheikh), format="json")
    assert reponse.status_code == 400
    reponse = client_a.post(f"{API}/absences", _corps(org.awa, org_b.cheikh), format="json")
    assert reponse.json()["code"] == "DELEGATAIRE_INVALIDE"
    # Candidats : aucun utilisateur de B ; « pour » d'un utilisateur de B refusé.
    noms = [c["nom"] for c in client_a.get(f"{API}/absences/candidats").json()]
    assert len(noms) == 5
    assert client_a.get(f"{API}/absences/candidats?pour={org_b.awa.pk}").status_code == 400
    # Ni l'absence de B par les routes de décision.
    reponse = client_a.post(
        f"/api/v1/absences/{absence_b['id']}/refuser", {"motif": "x"}, format="json"
    )
    assert reponse.status_code == 404
    assert _evenements(org.etab, "delegation.revoquee") == []
