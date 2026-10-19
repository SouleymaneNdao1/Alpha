"""Boîte « À traiter » : cycle de vie, visibilité, urgence, compteurs, API (tâche B8)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from freezegun import freeze_time

from alpha.audit.models import EvenementAudit
from alpha.taches import services
from alpha.taches.models import Action, Module, StatutTache, Tache
from alpha.taches.visibilite import annoter_urgence, bornes_urgence, visibles_pour
from alpha.tenancy.contexte import contexte_tenant
from tests.outils_b8 import instant, organisation_b8

pytestmark = pytest.mark.django_db


def _source():
    return ("tests.objet", uuid.uuid4())


def _ouvrir(org, **champs):
    champs.setdefault("module", Module.INTERNE)
    champs.setdefault("action", Action.DECIDER)
    champs.setdefault("titre", "40 postes informatiques")
    if "assigne_role" not in champs:
        champs.setdefault("assigne_utilisateur", org.awa)
    with contexte_tenant(org.etab.id):
        return services.ouvrir(champs.pop("source", None) or _source(), **champs)


def _actions_audit(etab, objet_id) -> list[str]:
    with contexte_tenant(etab.id):
        return list(
            EvenementAudit.objects.filter(objet_id=str(objet_id))
            .order_by("seq")
            .values_list("action", flat=True)
        )


# --- Cycle de vie ---------------------------------------------------------------------------


def test_cycle_de_vie_ouvrir_terminer(etab_a):
    org = organisation_b8(etab_a)
    source = _source()
    tache = _ouvrir(org, source=source, reference="ED-2026-0077", montant=Decimal("14600000"))
    assert tache.statut == StatutTache.OUVERTE

    # Idempotence : la même (source, action) renvoie la tâche existante, sans nouvel audit.
    deuxieme = _ouvrir(org, source=source, titre="autre titre")
    assert deuxieme.pk == tache.pk
    with contexte_tenant(etab_a.id):
        assert Tache.objects.count() == 1
        assert services.tache_ouverte(source, Action.DECIDER).pk == tache.pk

        fermee = services.terminer(source, Action.DECIDER, par=org.awa, resultat="VALIDEE")
        assert fermee.statut == StatutTache.TERMINEE
        assert fermee.terminee_par_id == org.awa.pk
        assert fermee.pour_compte_de_id is None
        assert fermee.terminee_le is not None
        assert not visibles_pour(org.awa).exists()
        # Idempotence de la fermeture.
        assert services.terminer(source, Action.DECIDER, par=org.awa) is None

        # Une fois fermée, la même source peut rouvrir une nouvelle tâche.
        nouvelle = services.ouvrir(
            source,
            module=Module.INTERNE,
            action=Action.DECIDER,
            titre="t",
            assigne_role=org.analyste,
        )
        assert nouvelle.pk != tache.pk
        annulees = services.annuler(source)
        assert [t.pk for t in annulees] == [nouvelle.pk]
        assert services.annuler(source) == []

    assert _actions_audit(etab_a, tache.pk) == ["tache.ouverte", "tache.terminee"]
    assert _actions_audit(etab_a, nouvelle.pk) == ["tache.ouverte", "tache.annulee"]


def test_reassigner_journalise(etab_a):
    org = organisation_b8(etab_a)
    tache = _ouvrir(org)
    with contexte_tenant(etab_a.id):
        services.reassigner(tache, assigne_utilisateur=org.cheikh)
        assert visibles_pour(org.cheikh).filter(pk=tache.pk).exists()
        assert not visibles_pour(org.awa).filter(pk=tache.pk).exists()
        with pytest.raises(ValueError):
            services.reassigner(tache, assigne_utilisateur=None)
    assert _actions_audit(etab_a, tache.pk)[-1] == "tache.reassignee"


def test_ouvrir_refuse_une_tache_sans_destinataire(etab_a):
    org = organisation_b8(etab_a)
    with contexte_tenant(etab_a.id), pytest.raises(ValueError):
        services.ouvrir(_source(), module=Module.INTERNE, action=Action.DECIDER, titre="t")
    with pytest.raises(ValueError):
        _ouvrir(org, assigne_unite=org.agence)  # unité sans rôle


# --- Visibilité par rôle et périmètre ----------------------------------------------------------


def test_visibilite_par_role_et_sous_arbre(etab_a):
    org = organisation_b8(etab_a)
    sur_agence = _ouvrir(org, assigne_role=org.analyste, assigne_unite=org.agence)
    sur_direction = _ouvrir(org, assigne_role=org.analyste, assigne_unite=org.direction)
    sans_unite = _ouvrir(org, assigne_role=org.analyste)
    with contexte_tenant(etab_a.id):
        # Cheikh (analyste sur la Direction) voit le sous-arbre ; Awa (Agence) pas la Direction.
        assert set(visibles_pour(org.cheikh).values_list("id", flat=True)) == {
            sur_agence.pk,
            sur_direction.pk,
            sans_unite.pk,
        }
        assert set(visibles_pour(org.awa).values_list("id", flat=True)) == {
            sur_agence.pk,
            sans_unite.pk,
        }
        # Fatou n'a aucun rôle ; l'admin n'a pas le rôle analyste.
        assert not visibles_pour(org.fatou).exists()
        assert not visibles_pour(org.admin).exists()
        assert all(t.par_delegation_de_id is None for t in visibles_pour(org.cheikh))


# --- Regroupement par urgence (Africa/Dakar, autour de minuit) ------------------------------------


def test_regroupement_par_urgence_autour_de_minuit_a_dakar(etab_a):
    org = organisation_b8(etab_a)
    # Dimanche 10/03/2030 23:59:30 à Dakar (UTC+0).
    with freeze_time("2030-03-10T23:59:30+00:00") as horloge:
        ce_soir = _ouvrir(org, echeance=instant("2030-03-10T23:59:59+00:00"), titre="ce soir")
        depassee = _ouvrir(org, echeance=instant("2030-03-10T08:00:00+00:00"), titre="matin")
        lundi = _ouvrir(org, echeance=instant("2030-03-11T10:00:00+00:00"), titre="lundi")
        mercredi = _ouvrir(org, echeance=instant("2030-03-13T10:00:00+00:00"), titre="mercredi")
        sans = _ouvrir(org, echeance=None, titre="sans échéance")

        def groupes():
            with contexte_tenant(etab_a.id):
                bornes = bornes_urgence()
                return {
                    t.titre: (t.groupe_ordre, bornes.retard_jours(t.echeance))
                    for t in annoter_urgence(visibles_pour(org.awa), bornes)
                }

        # Dimanche soir : la semaine s'achève ce soir ; lundi et mercredi sont « plus tard ».
        assert groupes() == {
            "matin": (0, 0),
            "ce soir": (1, None),
            "lundi": (3, None),
            "mercredi": (3, None),
            "sans échéance": (3, None),
        }

        # Lundi 00:00:30 : « ce soir » passe en retard d'un jour ; nouvelle semaine.
        horloge.move_to("2030-03-11T00:00:30+00:00")
        assert groupes() == {
            "matin": (0, 1),
            "ce soir": (0, 1),
            "lundi": (1, None),
            "mercredi": (2, None),
            "sans échéance": (3, None),
        }

        # Ordre : groupe, puis échéance croissante, puis création.
        with contexte_tenant(etab_a.id):
            ordre = list(
                annoter_urgence(visibles_pour(org.awa), bornes_urgence()).values_list(
                    "id", flat=True
                )
            )
        assert ordre == [depassee.pk, ce_soir.pk, lundi.pk, mercredi.pk, sans.pk]


def test_bornes_dans_le_fuseau_de_l_etablissement():
    import zoneinfo

    paris = zoneinfo.ZoneInfo("Europe/Paris")
    # 22:30 UTC = 23:30 à Paris (hiver) : « demain » commence à 23:00 UTC.
    bornes = bornes_urgence(instant("2030-03-12T22:30:00+00:00"), paris)
    assert bornes.demain == instant("2030-03-12T23:00:00+00:00")
    assert bornes.groupe_de(instant("2030-03-12T22:59:00+00:00")) == "AUJOURDHUI"
    assert bornes.groupe_de(instant("2030-03-12T23:30:00+00:00")) == "CETTE_SEMAINE"


# --- API ----------------------------------------------------------------------------------------


def test_api_liste_filtres_compteurs(etab_a, client_connecte):
    org = organisation_b8(etab_a)
    with freeze_time("2030-03-12T09:00:00+00:00"):  # mardi
        _ouvrir(org, echeance=instant("2030-03-11T18:00:00+00:00"), reference="ED-1")
        _ouvrir(org, echeance=instant("2030-03-12T18:00:00+00:00"), module=Module.CREDIT)
        _ouvrir(org, echeance=instant("2030-03-14T18:00:00+00:00"), titre="Contrat Sonatel")
        _ouvrir(org, echeance=None, assigne_role=org.analyste, assigne_unite=org.agence)
        client = client_connecte(org.awa)

        reponse = client.get("/api/v1/taches/")
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["count"] == 4
        premiere = corps["results"][0]
        assert premiere["groupe"] == "EN_RETARD"
        assert premiere["retard_jours"] == 1
        assert premiere["reference"] == "ED-1"
        assert premiere["module_libelle"] == "Décisions internes"
        assert premiere["action_libelle"] == "Décider"
        assert premiere["par_delegation_de"] is None
        assert [r["groupe"] for r in corps["results"]] == [
            "EN_RETARD",
            "AUJOURDHUI",
            "CETTE_SEMAINE",
            "PLUS_TARD",
        ]

        assert client.get("/api/v1/taches/?module=CREDIT").json()["count"] == 1
        assert client.get("/api/v1/taches/?groupe=PLUS_TARD").json()["count"] == 1
        assert client.get("/api/v1/taches/?q=sonatel").json()["count"] == 1
        assert client.get("/api/v1/taches/?groupe=DEMAIN").status_code == 400
        assert client.get("/api/v1/taches/?module=X").json()["code"] == "VALIDATION"

        compteurs = client.get("/api/v1/taches/compteurs/").json()
        assert compteurs == {
            "total": 4,
            "par_groupe": {"EN_RETARD": 1, "AUJOURDHUI": 1, "CETTE_SEMAINE": 1, "PLUS_TARD": 1},
            "par_module": {"CREDIT": 1, "INTERNE": 3},
        }
        # Cheikh ne voit que la tâche de rôle (sous-arbre de la Direction).
        assert client_connecte(org.cheikh).get("/api/v1/taches/compteurs/").json()["total"] == 1
        assert client_connecte(org.fatou).get("/api/v1/taches/compteurs/").json() == {
            "total": 0,
            "par_groupe": {"EN_RETARD": 0, "AUJOURDHUI": 0, "CETTE_SEMAINE": 0, "PLUS_TARD": 0},
            "par_module": {},
        }


def test_api_detail_404_si_non_visible(etab_a, client_connecte):
    org = organisation_b8(etab_a)
    tache = _ouvrir(org)
    assert client_connecte(org.awa).get(f"/api/v1/taches/{tache.pk}/").status_code == 200
    reponse = client_connecte(org.fatou).get(f"/api/v1/taches/{tache.pk}/")
    assert reponse.status_code == 404
    assert reponse.json()["code"] == "INTROUVABLE"


def test_api_exige_une_session(client_api):
    assert client_api.get("/api/v1/taches/").status_code == 401
    assert client_api.get("/api/v1/taches/compteurs/").status_code == 401


def test_api_refuse_le_super_admin(client_connecte):
    from tests.fabriques import UtilisateurFactory

    admin = UtilisateurFactory(super_admin=True)
    assert client_connecte(admin).get("/api/v1/taches/").status_code == 403
