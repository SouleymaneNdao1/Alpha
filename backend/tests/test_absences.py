"""Absences et délégations : parcours complet, règles P5, audit, tâches planifiées (tâche B8)."""

from __future__ import annotations

import uuid

import pytest
from freezegun import freeze_time

from alpha.audit.models import EvenementAudit
from alpha.delegations import services, tasks
from alpha.delegations.models import Absence, Delegation, StatutAbsence, StatutDelegation
from alpha.taches import services as taches
from alpha.taches.models import Action, Module, StatutTache, Tache
from alpha.taches.visibilite import visibles_pour
from alpha.tenancy.contexte import contexte_tenant
from tests.fabriques import UtilisateurFactory
from tests.outils_b8 import affecter, instant, organisation_b8

pytestmark = pytest.mark.django_db

T0 = "2030-03-04T08:00:00+00:00"  # lundi, avant l'absence
DEBUT = "2030-03-11T00:00:00+00:00"
FIN = "2030-03-16T00:00:00+00:00"


@pytest.fixture
def horloge():
    with freeze_time(T0) as h:
        yield h


@pytest.fixture
def org(etab_a, horloge):
    return organisation_b8(etab_a)


def _demande(client, delegataire, **champs):
    corps = {"debut": DEBUT, "fin": FIN, "motif": "CONGE", "delegataire_id": str(delegataire.pk)}
    corps.update(champs)
    return client.post("/api/v1/moi/absences/", corps, format="json")


def _audit(etab, *actions) -> list[str]:
    with contexte_tenant(etab.id):
        return list(
            EvenementAudit.objects.filter(action__in=actions)
            .order_by("seq")
            .values_list("action", flat=True)
        )


def _tache_directe(org, titre="Dossier CR-2030-0412"):
    """Tâche assignée nommément à Awa (l'absente)."""
    with contexte_tenant(org.etab.id):
        return taches.ouvrir(
            ("tests.dossier", uuid.uuid4()),
            module=Module.CREDIT,
            action=Action.DECIDER,
            titre=titre,
            assigne_utilisateur=org.awa,
        )


# --- Parcours complet ----------------------------------------------------------------------------


def test_parcours_absence_validation_delegation_visibilite_fin(org, horloge, client_connecte):
    tache_awa = _tache_directe(org)

    # 1. Awa déclare son absence et désigne Cheikh.
    reponse = _demande(client_connecte(org.awa), org.cheikh, commentaire="Congé annuel")
    assert reponse.status_code == 201, reponse.json()
    absence = reponse.json()
    assert absence["statut"] == "SOUMISE"
    assert absence["valideur"]["id"] == str(org.mamadou.pk)
    assert absence["delegation"]["statut"] == "EN_ATTENTE"
    assert absence["delegation"]["delegataire"]["nom"] == "Cheikh Badiane"

    # 2. Le responsable (Mamadou) a une tâche « Valider » vers /absences/{id}.
    client_mamadou = client_connecte(org.mamadou)
    a_traiter = client_mamadou.get("/api/v1/taches/").json()["results"]
    assert [(t["action"], t["lien"]) for t in a_traiter] == [
        ("VALIDER", f"/absences/{absence['id']}")
    ]
    assert a_traiter[0]["titre"] == "Absence · Awa Diop"
    assert client_mamadou.get(f"/api/v1/absences/{absence['id']}/").json()["peut_decider"]

    # 3. Validation : délégation ACTIVE (pas encore effective), tâche terminée.
    reponse = client_mamadou.post(f"/api/v1/absences/{absence['id']}/valider/", {}, format="json")
    assert reponse.status_code == 200, reponse.json()
    assert reponse.json()["statut"] == "VALIDEE"
    assert reponse.json()["delegation"]["statut"] == "ACTIVE"
    assert client_mamadou.get("/api/v1/taches/").json()["count"] == 0
    with contexte_tenant(org.etab.id):
        validation = Tache.objects.get(source_id=absence["id"])
        assert (validation.statut, validation.resultat) == (StatutTache.TERMINEE, "VALIDEE")
        # Avant le début, Cheikh ne voit pas encore les tâches d'Awa.
        assert not visibles_pour(org.cheikh).filter(pk=tache_awa.pk).exists()

    # 4. Pendant l'absence : visibilité « par délégation de Awa Diop ».
    horloge.move_to("2030-03-12T09:00:00+00:00")
    assert tasks.activer_delegations.delay().get() == 1
    client_cheikh = client_connecte(org.cheikh)
    visibles = client_cheikh.get("/api/v1/taches/").json()["results"]
    assert [(t["id"], t["par_delegation_de"]) for t in visibles] == [
        (str(tache_awa.pk), {"id": str(org.awa.pk), "nom": "Awa Diop"})
    ]
    recues = client_cheikh.get("/api/v1/moi/delegations-recues/").json()
    assert [(d["delegant"]["nom"], d["statut"], d["effective"]) for d in recues] == [
        ("Awa Diop", "ACTIVE", True)
    ]

    # Cheikh traite la tâche d'Awa : « pour le compte de » Awa.
    with contexte_tenant(org.etab.id):
        fermee = taches.terminer(
            (tache_awa.source_type, tache_awa.source_id), Action.DECIDER, par=org.cheikh
        )
        assert fermee.pour_compte_de_id == org.awa.pk
    deuxieme = _tache_directe(org, "Dossier CR-2030-0413")

    # 5. Après la fin : visibilité retirée aussitôt, puis clôture planifiée.
    horloge.move_to("2030-03-16T00:00:01+00:00")
    assert client_connecte(org.cheikh).get("/api/v1/taches/").json()["count"] == 0
    assert tasks.cloturer_delegations.delay().get() == 1
    with contexte_tenant(org.etab.id):
        delegation = Delegation.objects.get(absence_id=absence["id"])
        assert delegation.statut == StatutDelegation.TERMINEE
        assert delegation.terminee_le is not None
        assert visibles_pour(org.awa).filter(pk=deuxieme.pk).exists()

    assert _audit(
        org.etab,
        "absence.soumise",
        "absence.validee",
        "delegation.active",
        "delegation.terminee",
    ) == ["absence.soumise", "absence.validee", "delegation.active", "delegation.terminee"]


def test_validation_pendant_l_absence_active_aussitot(org, horloge, client_connecte):
    absence = _demande(client_connecte(org.awa), org.cheikh).json()
    horloge.move_to("2030-03-12T09:00:00+00:00")
    client_connecte(org.mamadou).post(f"/api/v1/absences/{absence['id']}/valider/")
    with contexte_tenant(org.etab.id):
        delegation = Delegation.objects.get(absence_id=absence["id"])
        assert delegation.activee_le is not None
    # Rien à faire pour la tâche planifiée : déjà datée à la validation.
    assert tasks.activer_delegations.delay().get() == 1  # un établissement parcouru
    assert _audit(org.etab, "delegation.active") == ["delegation.active"]


# --- Règles P5 ----------------------------------------------------------------------------------


def test_refus_d_un_delegataire_aux_pouvoirs_insuffisants(org, client_connecte):
    reponse = _demande(client_connecte(org.awa), org.fatou)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "POUVOIRS_INSUFFISANTS"
    # Un analyste sur une AUTRE agence ne couvre pas l'Agence Plateau.
    from tests.fabriques import UniteOrganisationnelleFactory

    autre = UniteOrganisationnelleFactory(etablissement=org.etab, parent=org.direction)
    affecter(org.fatou, org.analyste, autre)
    assert _demande(client_connecte(org.awa), org.fatou).json()["code"] == "POUVOIRS_INSUFFISANTS"
    # Les permissions système comptent aussi : l'admin ne peut déléguer qu'à un admin.
    reponse = _demande(client_connecte(org.admin), org.cheikh)
    assert reponse.json()["code"] == "POUVOIRS_INSUFFISANTS"
    assert reponse.json()["details"]["permissions_manquantes"] == ["admin.absences"]
    with contexte_tenant(org.etab.id):
        assert Absence.objects.count() == 0


def test_delegation_limitee_a_un_role(org, client_connecte):
    client = client_connecte(org.awa)
    reponse = _demande(client, org.cheikh, role_id=str(org.role_admin.pk))
    assert reponse.json()["code"] == "ROLE_NON_DETENU"
    reponse = _demande(client, org.cheikh, role_id=str(org.analyste.pk))
    assert reponse.status_code == 201
    assert reponse.json()["delegation"]["role"]["libelle"] == "Analyste crédit"


def test_delegataire_invalide(org, client_connecte):
    client = client_connecte(org.awa)
    assert _demande(client, org.awa).json()["code"] == "DELEGATAIRE_INVALIDE"
    corps = {"debut": DEBUT, "fin": FIN, "motif": "CONGE", "delegataire_id": str(uuid.uuid4())}
    assert client.post("/api/v1/moi/absences/", corps, format="json").status_code == 400


def test_sous_delegation_interdite(org, horloge, client_connecte):
    # Awa → Cheikh, validée.
    absence = _demande(client_connecte(org.awa), org.cheikh).json()
    client_connecte(org.mamadou).post(f"/api/v1/absences/{absence['id']}/valider/")

    # Cheikh, délégataire sur la période, ne peut pas redéléguer à Mamadou.
    reponse = _demande(client_connecte(org.cheikh), org.mamadou, debut="2030-03-13T00:00:00Z")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "SOUS_DELEGATION_INTERDITE"

    # Mamadou ne peut pas choisir Awa (absente, déléguante) sur une période qui chevauche.
    reponse = _demande(client_connecte(org.mamadou), org.awa)
    assert reponse.json()["code"] == "SOUS_DELEGATION_INTERDITE"

    # Hors période, c'est possible.
    reponse = _demande(
        client_connecte(org.cheikh),
        org.mamadou,
        debut="2030-04-01T00:00:00Z",
        fin="2030-04-05T00:00:00Z",
    )
    assert reponse.status_code == 201

    # La visibilité n'est pas transitive : si Mamadou délègue à Cheikh, Cheikh ne
    # voit pas les tâches de ceux qui ont délégué à Mamadou (et inversement).
    horloge.move_to("2030-03-12T09:00:00+00:00")
    tache_awa = _tache_directe(org)
    with contexte_tenant(org.etab.id):
        assert visibles_pour(org.cheikh).filter(pk=tache_awa.pk).exists()
        assert not visibles_pour(org.mamadou).filter(pk=tache_awa.pk).exists()


def test_delegation_bornee_dans_le_temps(org, client_connecte):
    client = client_connecte(org.awa)
    reponse = _demande(client, org.cheikh, fin=DEBUT)
    assert reponse.status_code == 400
    assert "fin" in reponse.json()["details"]
    reponse = _demande(client, org.cheikh, debut="2030-01-01T00:00:00Z", fin="2030-02-01T00:00:00Z")
    assert reponse.json()["details"]["fin"] == ["La fin doit être dans le futur."]
    reponse = _demande(client, org.cheikh, fin="2031-06-01T00:00:00Z")
    assert reponse.status_code == 400
    corps = {"debut": DEBUT, "motif": "CONGE", "delegataire_id": str(org.cheikh.pk)}
    assert client.post("/api/v1/moi/absences/", corps, format="json").status_code == 400


def test_chevauchement(org, client_connecte):
    client = client_connecte(org.awa)
    assert _demande(client, org.cheikh).status_code == 201
    reponse = _demande(client, org.cheikh, debut="2030-03-15T00:00:00Z", fin="2030-03-20T00:00:00Z")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "CHEVAUCHEMENT"


def test_contrainte_d_exclusion_en_base(org):
    """Deux délégations en cours du même délégant sur la même période : refus SQL."""
    from django.db import IntegrityError, transaction

    with contexte_tenant(org.etab.id):
        absence = Absence.objects.create(
            utilisateur=org.awa, debut=instant(DEBUT), fin=instant(FIN), motif="CONGE"
        )
        Delegation.objects.create(
            absence=absence,
            delegant=org.awa,
            delegataire=org.cheikh,
            debut=instant(DEBUT),
            fin=instant(FIN),
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Delegation.objects.create(
                absence=absence,
                delegant=org.awa,
                delegataire=org.mamadou,
                debut=instant("2030-03-12T00:00:00+00:00"),
                fin=instant("2030-03-13T00:00:00+00:00"),
            )


# --- Valideur et décisions ------------------------------------------------------------------------


def test_valideur_par_defaut_administrateur(org, client_connecte):
    # Cheikh n'a pas de responsable : valideur = l'administrateur des absences.
    reponse = _demande(client_connecte(org.cheikh), org.mamadou)
    assert reponse.json()["valideur"]["id"] == str(org.admin.pk)


def test_aucun_valideur(etab_b, horloge, client_connecte):
    seul = UtilisateurFactory(etablissement=etab_b, prenom="Seul", nom="Agent")
    autre = UtilisateurFactory(etablissement=etab_b, prenom="Autre", nom="Agent")
    reponse = _demande(client_connecte(seul), autre)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "AUCUN_VALIDEUR"


def test_droits_de_decision(org, client_connecte):
    absence = _demande(client_connecte(org.awa), org.cheikh).json()
    url = f"/api/v1/absences/{absence['id']}"
    # L'absente voit sa demande mais ne peut pas la valider (403) ; un tiers : 404.
    reponse_awa = client_connecte(org.awa).post(f"{url}/valider/")
    assert reponse_awa.status_code == 403
    assert client_connecte(org.awa).get(f"{url}/").json()["peut_decider"] is False
    assert client_connecte(org.fatou).get(f"{url}/").status_code == 404
    assert client_connecte(org.fatou).post(f"{url}/valider/").status_code == 404
    # Un titulaire de admin.absences peut refuser ; le motif est obligatoire.
    client_admin = client_connecte(org.admin)
    assert client_admin.post(f"{url}/refuser/", {}, format="json").status_code == 400
    reponse = client_admin.post(f"{url}/refuser/", {"motif": "Période chargée"}, format="json")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "REFUSEE"
    assert reponse.json()["delegation"]["statut"] == "REFUSEE"
    assert client_admin.post(f"{url}/valider/").json()["code"] == "STATUT_INVALIDE"
    assert _audit(org.etab, "absence.soumise", "absence.refusee") == [
        "absence.soumise",
        "absence.refusee",
    ]


def test_delegataire_du_valideur_decide_pour_son_compte(org, horloge, client_connecte):
    # Mamadou (responsable d'Awa) s'absente et délègue à Cheikh ; l'admin valide.
    absence_m = _demande(client_connecte(org.mamadou), org.cheikh).json()
    client_connecte(org.admin).post(f"/api/v1/absences/{absence_m['id']}/valider/")
    # Awa demande ensuite une absence (Mamadou est son valideur) avec Fatou analyste.
    affecter(org.fatou, org.analyste, org.agence)
    absence_a = _demande(
        client_connecte(org.awa),
        org.fatou,
        debut="2030-03-20T00:00:00Z",
        fin="2030-03-22T00:00:00Z",
    ).json()
    horloge.move_to("2030-03-12T09:00:00+00:00")
    client_cheikh = client_connecte(org.cheikh)
    a_traiter = client_cheikh.get("/api/v1/taches/").json()["results"]
    assert a_traiter[0]["par_delegation_de"]["nom"] == "Mamadou Sow"
    reponse = client_cheikh.post(f"/api/v1/absences/{absence_a['id']}/valider/")
    assert reponse.status_code == 200, reponse.json()
    with contexte_tenant(org.etab.id):
        tache = Tache.objects.get(source_id=absence_a["id"])
        assert tache.terminee_par_id == org.cheikh.pk
        assert tache.pour_compte_de_id == org.mamadou.pk


# --- Annulation et liste ----------------------------------------------------------------------------


def test_annulation_avant_et_pendant(org, horloge, client_connecte):
    client_awa = client_connecte(org.awa)
    soumise = _demande(client_awa, org.cheikh).json()
    reponse = client_awa.post(f"/api/v1/moi/absences/{soumise['id']}/annuler/")
    assert reponse.json()["statut"] == "ANNULEE"
    assert reponse.json()["delegation"]["statut"] == "ANNULEE"
    assert client_connecte(org.mamadou).get("/api/v1/taches/").json()["count"] == 0
    # Un tiers ne peut pas l'annuler (404).
    assert client_connecte(org.cheikh).post(
        f"/api/v1/moi/absences/{soumise['id']}/annuler/"
    ).status_code == 404

    validee = _demande(client_awa, org.cheikh).json()
    client_connecte(org.mamadou).post(f"/api/v1/absences/{validee['id']}/valider/")
    horloge.move_to("2030-03-12T09:00:00+00:00")
    client_awa = client_connecte(org.awa)
    reponse = client_awa.post(f"/api/v1/moi/absences/{validee['id']}/annuler/")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "VALIDEE"
    assert reponse.json()["fin"].startswith("2030-03-12T09:00:00")
    assert reponse.json()["delegation"]["statut"] == "TERMINEE"
    assert client_awa.post(f"/api/v1/moi/absences/{validee['id']}/annuler/").status_code == 409

    liste = client_awa.get("/api/v1/moi/absences/").json()
    assert liste["count"] == 2
    assert client_awa.get("/api/v1/moi/absences/?statut=ANNULEE").json()["count"] == 1
    assert client_awa.get("/api/v1/moi/absences/?statut=X").status_code == 400


def test_delegataires_possibles(org, client_connecte):
    reponse = client_connecte(org.awa).get("/api/v1/moi/delegataires-possibles/")
    lignes = {ligne["nom"]: ligne for ligne in reponse.json()}
    assert "Awa Diop" not in lignes
    assert lignes["Cheikh Badiane"]["pouvoirs_suffisants"] is True
    assert lignes["Cheikh Badiane"]["role_principal"] == "Analyste crédit"
    assert lignes["Fatou Ndiaye"]["pouvoirs_suffisants"] is False
    filtre = client_connecte(org.awa).get("/api/v1/moi/delegataires-possibles/?q=badi").json()
    assert [ligne["nom"] for ligne in filtre] == ["Cheikh Badiane"]


# --- Isolation A/B -------------------------------------------------------------------------------


def test_isolation_entre_etablissements(org, etab_b, client_connecte):
    absence = _demande(client_connecte(org.awa), org.cheikh).json()
    tache = _tache_directe(org)
    intrus = UtilisateurFactory(etablissement=etab_b, prenom="Moussa", nom="Fall")
    client_b = client_connecte(intrus)
    for url in (
        f"/api/v1/absences/{absence['id']}/",
        f"/api/v1/taches/{tache.pk}/",
    ):
        assert client_b.get(url).status_code == 404
    for url in (
        f"/api/v1/absences/{absence['id']}/valider/",
        f"/api/v1/absences/{absence['id']}/refuser/",
        f"/api/v1/moi/absences/{absence['id']}/annuler/",
    ):
        assert client_b.post(url, {"motif": "x"}, format="json").status_code == 404
    # Un délégataire d'un autre établissement est inconnu.
    reponse = _demande(client_b, org.cheikh)
    assert reponse.json()["code"] == "DELEGATAIRE_INVALIDE"
    assert client_b.get("/api/v1/taches/compteurs/").json()["total"] == 0
    assert client_b.get("/api/v1/moi/delegataires-possibles/").json() == []


# --- Tâches planifiées --------------------------------------------------------------------------------


def test_taches_planifiees_idempotentes(org, horloge, client_connecte):
    absence = _demande(client_connecte(org.awa), org.cheikh).json()
    client_connecte(org.mamadou).post(f"/api/v1/absences/{absence['id']}/valider/")

    with contexte_tenant(org.etab.id):
        assert services.activer_delegations_echues() == 0  # pas encore commencée
    horloge.move_to("2030-03-11T00:02:00+00:00")
    tasks.activer_delegations_etablissement.delay(str(org.etab.id))
    tasks.activer_delegations_etablissement.delay(str(org.etab.id))
    with contexte_tenant(org.etab.id):
        assert services.activer_delegations_echues() == 0
        assert services.cloturer_delegations_echues() == 0

    horloge.move_to("2030-03-16T00:03:00+00:00")
    tasks.cloturer_delegations.delay()
    tasks.cloturer_delegations.delay()
    with contexte_tenant(org.etab.id):
        assert services.cloturer_delegations_echues() == 0
        assert services.activer_delegations_echues() == 0
        assert Delegation.objects.get().statut == StatutDelegation.TERMINEE
        assert Absence.objects.get().statut == StatutAbsence.VALIDEE
    assert _audit(org.etab, "delegation.active", "delegation.terminee") == [
        "delegation.active",
        "delegation.terminee",
    ]


def test_tache_planifiee_sans_etablissement_refusee():
    from alpha.tenancy.exceptions import TenantNonDefini

    with pytest.raises(TenantNonDefini):
        tasks.cloturer_delegations_etablissement.delay(None)
