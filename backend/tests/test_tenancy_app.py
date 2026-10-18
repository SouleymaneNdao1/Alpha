"""Barrière applicative (tâche B2) : TenantManager, TenantModel.save, contexte_tenant,
middlewares et décorateur tache_tenant.

Ces tests passent par la connexion ``default`` (alpha_app, montage T1) : la RLS
s'applique AUSSI. Pour vérifier qu'une écriture a bien eu lieu (ou non), on relit
donc sous le contexte de l'établissement concerné.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection, connections, transaction
from django.test import Client, override_settings

from alpha.core import contexte
from alpha.tenancy.celery import tache_tenant
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.exceptions import TenantNonDefini, ViolationTenant
from alpha.tenancy.middleware import lire_contexte_session
from alpha.tenancy.models import Etablissement, ParametresEtablissement
from tests.appli_test.models import NoteTest

from .conftest import creer_etablissement

pytestmark = pytest.mark.django_db


def _variables_sql() -> tuple[str, str]:
    """(établissement, portée) tels que vus par les politiques RLS (fonctions app_*)."""
    with connection.cursor() as curseur:
        curseur.execute("SELECT coalesce(app_current_tenant()::text, ''), app_scope()")
        return curseur.fetchone()


# --- TenantManager ------------------------------------------------------------------------


@pytest.mark.parametrize("modele", [NoteTest, ParametresEtablissement])
def test_tenant_manager_leve_une_erreur_sans_contexte(etab_a, modele):
    with pytest.raises(TenantNonDefini):
        list(modele.objects.all())
    with pytest.raises(TenantNonDefini):
        modele.objects.count()


def test_tenant_manager_filtre_sur_le_contexte(etab_a, etab_b):
    for etab in (etab_a, etab_b):
        with contexte_tenant(etab.id):
            NoteTest.objects.create(texte=etab.code)
    with contexte_tenant(etab_a.id):
        assert [n.texte for n in NoteTest.objects.all()] == ["banque-a"]
        assert list(ParametresEtablissement.objects.values_list("etablissement", flat=True)) == [
            etab_a.id
        ]
    with contexte_tenant(etab_b.id):
        assert [n.texte for n in NoteTest.objects.all()] == ["sfd-b"]


def test_parametres_valeurs_par_defaut_validees(etab_a):
    """Décisions P2 et P3 (§ 10) : valeurs par défaut des réglages par établissement."""
    with contexte_tenant(etab_a.id):
        p = ParametresEtablissement.objects.get()
    assert p.inactivite_session_min == 15
    assert p.duree_max_session_h == 12
    assert p.validite_invitation_h == 72
    assert p.validite_reinit_mdp_min == 30
    assert p.tentatives_max == 5
    assert p.verrouillage_min == 15
    assert p.verrouillages_max_24h == 3
    assert p.mdp_longueur_min == 12
    assert p.mdp_historique == 5
    assert p.mdp_expiration_jours is None  # pas d'expiration périodique par défaut
    assert p.retention_audit_annees == 10


# --- TenantModel.save / delete / bulk_create ------------------------------------------------------


def test_save_renseigne_l_etablissement_courant(etab_a):
    with contexte_tenant(etab_a.id):
        note = NoteTest(texte="x")
        note.save()
    assert note.etablissement_id == etab_a.id


def test_save_refuse_un_autre_etablissement(etab_a, etab_b):
    with contexte_tenant(etab_a.id), pytest.raises(ViolationTenant):
        NoteTest(texte="intrus", etablissement=etab_b).save()
    with contexte_tenant(etab_b.id):
        assert NoteTest.objects.count() == 0


def test_save_refuse_sans_contexte(etab_a):
    with pytest.raises(TenantNonDefini):
        NoteTest(texte="x", etablissement=etab_a).save()


def test_modifier_une_ligne_d_un_autre_etablissement_refuse(etab_a, etab_b):
    with contexte_tenant(etab_b.id):
        note_b = NoteTest.objects.create(texte="b")
    with contexte_tenant(etab_a.id):
        note_b.texte = "pirate"
        with pytest.raises(ViolationTenant):
            note_b.save()
        with pytest.raises(ViolationTenant):
            note_b.delete()


def test_bulk_create_controle_l_etablissement(etab_a, etab_b):
    with contexte_tenant(etab_a.id):
        NoteTest.objects.bulk_create([NoteTest(texte="1"), NoteTest(texte="2")])
        with pytest.raises(ViolationTenant):
            NoteTest.objects.bulk_create([NoteTest(texte="3", etablissement=etab_b)])
        assert NoteTest.objects.count() == 2
    with contexte_tenant(etab_b.id):
        assert NoteTest.objects.count() == 0


# --- contexte_tenant ------------------------------------------------------------------------


def test_contexte_tenant_restaure_la_valeur_precedente(etab_a, etab_b):
    assert _variables_sql() == ("", "anonymous")
    with contexte_tenant(etab_a.id):
        assert contexte.tenant_courant() == etab_a.id
        assert _variables_sql() == (str(etab_a.id), "tenant")
        with contexte_tenant(etab_b.id):
            assert contexte.tenant_courant() == etab_b.id
            assert _variables_sql() == (str(etab_b.id), "tenant")
        # Retour à A, côté application ET côté PostgreSQL.
        assert contexte.tenant_courant() == etab_a.id
        assert contexte.scope_courant() == "tenant"
        assert _variables_sql() == (str(etab_a.id), "tenant")
        with contexte_tenant(None, scope=contexte.SCOPE_WORKER):
            assert _variables_sql() == ("", "worker")
        assert _variables_sql() == (str(etab_a.id), "tenant")
    assert contexte.tenant_courant() is None
    assert contexte.scope_courant() == "anonymous"


def test_contexte_tenant_restaure_aussi_apres_une_exception(etab_a, etab_b):
    with contexte_tenant(etab_a.id):
        with pytest.raises(ZeroDivisionError), contexte_tenant(etab_b.id):
            NoteTest.objects.create(texte="annulée")
            raise ZeroDivisionError
        assert contexte.tenant_courant() == etab_a.id
        # Le point de sauvegarde annulé rétablit les variables SQL… et annule l'écriture.
        assert _variables_sql() == (str(etab_a.id), "tenant")
    with contexte_tenant(etab_b.id):
        assert NoteTest.objects.count() == 0


def test_contexte_tenant_conserve_l_utilisateur_par_defaut(etab_a):
    utilisateur = uuid.uuid4()
    with contexte.contexte(utilisateur=utilisateur), contexte_tenant(etab_a.id):
        assert contexte.utilisateur_courant() == utilisateur
    with contexte_tenant(etab_a.id, utilisateur_id=None):
        assert contexte.utilisateur_courant() is None


@pytest.mark.parametrize(
    ("etablissement_id", "scope"),
    [
        (None, "tenant"),
        (uuid.uuid4(), "worker"),
        (uuid.uuid4(), "platform"),
        (uuid.uuid4(), "inconnue"),
        ("pas-un-uuid", "tenant"),
    ],
)
def test_contexte_tenant_refuse_un_contexte_incoherent(etablissement_id, scope):
    with pytest.raises(ValueError), contexte_tenant(etablissement_id, scope=scope):
        pass  # pragma: no cover


def test_contexte_tenant_refuse_un_objet_orm(etab_a):
    with pytest.raises(ValueError), contexte_tenant(etab_a):
        pass  # pragma: no cover


# --- Middlewares --------------------------------------------------------------------------


def _changer_statut(etablissement: Etablissement, statut: str) -> None:
    """Changement de statut : écriture réservée à la portée « platform » (RLS)."""
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
        Etablissement.objects.filter(id=etablissement.id).update(statut=statut)


def _client_tenant(etablissement: Etablissement, scope: str = "tenant") -> Client:
    client = Client()
    session = client.session
    session["tenant_id"] = str(etablissement.id)
    session["scope"] = scope
    session.save()
    client.cookies["alpha_sid"] = session.session_key
    return client


@pytest.mark.django_db(transaction=True)
@override_settings(ROOT_URLCONF="tests.appli_test.vues")
def test_le_contexte_ne_fuit_pas_d_une_requete_a_l_autre(etab_a):
    """Connexion persistante (CONN_MAX_AGE > 0) : la requête suivante ne voit rien de A."""
    reglages = connections["default"].settings_dict
    ancien = reglages["CONN_MAX_AGE"]
    connection.close()
    reglages["CONN_MAX_AGE"] = 60
    try:
        r1 = _client_tenant(etab_a).get("/contexte/").json()
        assert r1["tenant"] == r1["tenant_sql"] == str(etab_a.id)
        assert r1["scope"] == r1["scope_sql"] == "tenant"

        r2 = Client().get("/contexte/").json()
        assert r2["pid"] == r1["pid"]  # même connexion PostgreSQL réutilisée
        assert r2["tenant"] == r2["tenant_sql"] == ""
        assert r2["scope"] == r2["scope_sql"] == "anonymous"

        # Hors requête, sur la même connexion : aucune trace du contexte.
        assert connection.connection is not None
        assert _variables_sql() == ("", "anonymous")
        assert contexte.tenant_courant() is None
    finally:
        reglages["CONN_MAX_AGE"] = ancien
        connection.close()


@pytest.mark.parametrize(
    ("session", "attendu"),
    [
        ({}, (None, "anonymous", None)),
        ({"scope": "tenant"}, (None, "anonymous", None)),  # tenant manquant
        ({"tenant_id": "pas-un-uuid", "scope": "tenant"}, (None, "anonymous", None)),
        ({"tenant_id": str(uuid.UUID(int=1)), "scope": "platform"}, (None, "anonymous", None)),
        ({"tenant_id": str(uuid.UUID(int=1))}, (None, "anonymous", None)),  # scope absent
        ({"scope": "platform"}, (None, "platform", None)),
        (
            {"tenant_id": str(uuid.UUID(int=1)), "scope": "tenant"},
            (uuid.UUID(int=1), "tenant", None),
        ),
    ],
)
def test_lecture_du_contexte_de_session(rf, session, attendu):
    requete = rf.get("/")
    requete.session = session
    assert lire_contexte_session(requete) == attendu


@override_settings(ROOT_URLCONF="tests.appli_test.vues")
def test_statut_lecture_seule_refuse_les_ecritures(etab_a):
    _changer_statut(etab_a, "LECTURE_SEULE")
    client = _client_tenant(etab_a)
    assert client.get("/ecriture/").status_code == 200
    reponse = client.post("/ecriture/")
    assert reponse.status_code == 423
    assert reponse.json()["code"] == "ETABLISSEMENT_LECTURE_SEULE"
    # La déconnexion reste possible.
    assert client.post("/api/v1/auth/deconnexion").status_code == 200


@pytest.mark.parametrize("statut", ["SUSPENDU", "ARCHIVE"])
@override_settings(ROOT_URLCONF="tests.appli_test.vues")
def test_statut_suspendu_refuse_tout(etab_a, statut):
    _changer_statut(etab_a, statut)
    client = _client_tenant(etab_a)
    reponse = client.get("/contexte/")
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "ETABLISSEMENT_SUSPENDU"
    assert client.post("/api/v1/auth/deconnexion").status_code == 200


# --- Décorateur tache_tenant ------------------------------------------------------------------


@tache_tenant()
def _tache_lire_contexte(etablissement_id):
    with connection.cursor() as curseur:
        curseur.execute("SELECT current_setting('app.current_tenant', true)")
        sql = curseur.fetchone()[0]
    return {
        "tenant": str(contexte.tenant_courant()),
        "scope": contexte.scope_courant(),
        "utilisateur": contexte.utilisateur_courant(),
        "sql": sql,
        "en_transaction": connection.in_atomic_block,
        "notes": NoteTest.objects.count(),
    }


def test_tache_tenant_pose_le_contexte(etab_a, etab_b):
    with contexte_tenant(etab_b.id):
        NoteTest.objects.create(texte="b")
    with contexte.contexte(utilisateur=uuid.uuid4()):
        resultat = _tache_lire_contexte.apply(args=[str(etab_a.id)]).get()
    assert resultat == {
        "tenant": str(etab_a.id),
        "scope": "tenant",
        "utilisateur": None,
        "sql": str(etab_a.id),
        "en_transaction": True,
        "notes": 0,
    }
    assert contexte.tenant_courant() is None
    assert _tache_lire_contexte.queue == "defaut"


@pytest.mark.parametrize("valeur", [None, ""])
def test_tache_tenant_sans_etablissement_refusee(valeur):
    with pytest.raises(TenantNonDefini):
        _tache_lire_contexte.apply(args=[valeur]).get()


def test_tache_tenant_refuse_un_objet_orm(etab_a):
    with pytest.raises(ValueError):
        _tache_lire_contexte(etab_a)


def test_tache_tenant_est_atomique(etab_a):
    @tache_tenant()
    def _tache_qui_echoue(etablissement_id):
        NoteTest.objects.create(texte="annulée")
        raise RuntimeError("échec")

    with transaction.atomic(), pytest.raises(RuntimeError):
        _tache_qui_echoue(str(etab_a.id))
    with contexte_tenant(etab_a.id):
        assert NoteTest.objects.count() == 0


def test_creer_etablissement_outil(db):
    etab = creer_etablissement("pme-c", type="PME")
    with contexte_tenant(etab.id):
        assert ParametresEtablissement.objects.filter(etablissement=etab).exists()
