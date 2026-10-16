"""RLS au niveau SQL, connecté en alpha_app (tâche B2).

Critère de fin de B2 : « RLS active ; requête sans contexte = 0 ligne ».

Ces tests passent par la connexion ``applicatif`` (alpha_app, NOBYPASSRLS) :
ils vérifient la seconde barrière indépendamment du filtrage applicatif.
"""

from __future__ import annotations

import uuid
from importlib import import_module

import pytest
from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.test import override_settings

from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement, ParametresEtablissement
from tests.appli_test.models import NoteTest

from .conftest import ALIAS_APP, BASES_APP

pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_APP)

TABLES_TENANT = ("parametres_etablissement", "note_test")


def _sql(requete: str, params=None) -> list[tuple]:
    with connections[ALIAS_APP].cursor() as curseur:
        curseur.execute(requete, params or [])
        return curseur.fetchall() if curseur.description else []


def _compter(table: str) -> int:
    return _sql(f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - noms de table fixes


def _refuse(requete: str, params=None, *, motif: str) -> None:
    """La requête doit échouer en alpha_app ; le point de sauvegarde isole l'échec."""
    with pytest.raises(DatabaseError, match=motif), transaction.atomic(using=ALIAS_APP):
        _sql(requete, params)


@pytest.fixture
def donnees(etab_a, etab_b):
    """Deux établissements, leurs paramètres et deux notes chacun (validés par alpha_owner)."""
    for etab in (etab_a, etab_b):
        with contexte_tenant(etab.id):
            NoteTest.objects.create(texte=f"note 1 de {etab.code}")
            NoteTest.objects.create(texte=f"note 2 de {etab.code}")
    return etab_a, etab_b


def test_connexion_applicative_sans_bypassrls():
    role, bypass, superuser = _sql(
        "SELECT current_user, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
    )[0]
    assert role == settings.ALPHA_DB_APP_ROLE
    assert bypass is False
    assert superuser is False


# --- Sans contexte : zéro ligne ----------------------------------------------------------


@pytest.mark.parametrize("table", [*TABLES_TENANT, "etablissement"])
def test_sans_contexte_zero_ligne(donnees, table):
    assert _compter(table) == 0
    with transaction.atomic(using=ALIAS_APP):  # même dans une transaction sans set_config
        assert _compter(table) == 0


def test_sans_contexte_zero_ligne_meme_avec_le_manager_global(donnees):
    # objets_globaux n'est pas filtré par l'application : la RLS reste la barrière.
    assert NoteTest.objets_globaux.using(ALIAS_APP).count() == 0
    assert ParametresEtablissement.objets_globaux.using(ALIAS_APP).count() == 0


def test_alpha_owner_voit_tout_bypassrls(donnees):
    # Témoin : le propriétaire (migrations, exploitation) traverse les établissements.
    assert NoteTest.objets_globaux.count() == 4


# --- Avec le contexte A : seulement les lignes de A ----------------------------------------


def test_contexte_a_seulement_les_lignes_de_a(donnees):
    etab_a, _ = donnees
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        lignes = _sql("SELECT DISTINCT etablissement_id FROM note_test")
        assert lignes == [(etab_a.id,)]
        assert _compter("note_test") == 2
        assert _sql("SELECT etablissement_id FROM parametres_etablissement") == [(etab_a.id,)]
        assert _sql("SELECT id FROM etablissement") == [(etab_a.id,)]
        # Même via le manager non filtré : la RLS ne laisse passer que A.
        ids = set(NoteTest.objets_globaux.using(ALIAS_APP).values_list("etablissement", flat=True))
        assert ids == {etab_a.id}
    # Le contexte est local à la transaction : plus rien après.
    assert _compter("note_test") == 0


def test_variables_sql_posees_puis_effacees(donnees):
    etab_a, _ = donnees
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        assert _sql("SELECT app_current_tenant(), app_scope()") == [(etab_a.id, "tenant")]
    assert _sql("SELECT app_current_tenant(), app_scope(), app_current_user()") == [
        (None, "anonymous", None)
    ]


# --- Écritures croisées refusées --------------------------------------------------------------


def test_insertion_avec_l_etablissement_b_sous_contexte_a_refusee(donnees):
    etab_a, etab_b = donnees
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        _refuse(
            "INSERT INTO note_test (id, etablissement_id, texte) VALUES (%s, %s, 'intrus')",
            [uuid.uuid4(), etab_b.id],
            motif="row-level security",
        )
        # La même insertion pour A est acceptée.
        _sql(
            "INSERT INTO note_test (id, etablissement_id, texte) VALUES (%s, %s, 'ok')",
            [uuid.uuid4(), etab_a.id],
        )
    assert NoteTest.objets_globaux.filter(etablissement=etab_b).count() == 2


def test_insertion_sans_contexte_refusee(donnees):
    etab_a, _ = donnees
    _refuse(
        "INSERT INTO note_test (id, etablissement_id, texte) VALUES (%s, %s, 'x')",
        [uuid.uuid4(), etab_a.id],
        motif="row-level security",
    )


def test_deplacer_une_ligne_vers_b_refuse_et_lignes_de_b_intouchables(donnees):
    etab_a, etab_b = donnees
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        _refuse(
            "UPDATE note_test SET etablissement_id = %s",
            [etab_b.id],
            motif="row-level security",
        )
        with connections[ALIAS_APP].cursor() as curseur:
            curseur.execute(
                "UPDATE note_test SET texte = 'pirate' WHERE etablissement_id = %s", [etab_b.id]
            )
            assert curseur.rowcount == 0
            curseur.execute("DELETE FROM note_test WHERE etablissement_id = %s", [etab_b.id])
            assert curseur.rowcount == 0
    assert NoteTest.objets_globaux.filter(etablissement=etab_b).count() == 2


# --- Table etablissement (politiques spécifiques) -------------------------------------------------


def test_etablissement_portee_worker_voit_la_liste(donnees):
    with contexte_tenant(None, scope=contexte.SCOPE_WORKER, using=ALIAS_APP):
        assert _compter("etablissement") == 2
        # … mais aucune donnée d'établissement.
        assert _compter("note_test") == 0


def test_etablissement_ecriture_reservee_a_la_plateforme(donnees):
    etab_a, _ = donnees
    insertion = (
        "INSERT INTO etablissement (id, code, raison_sociale, type, pays, statut, fuseau_horaire,"
        " cree_le, modifie_le) VALUES (%s, %s, 'X', 'PME', 'SN', 'ACTIF', 'Africa/Dakar',"
        " now(), now())"
    )
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        _refuse(insertion, [uuid.uuid4(), "intrus"], motif="row-level security")
        with connections[ALIAS_APP].cursor() as curseur:
            curseur.execute("UPDATE etablissement SET raison_sociale = 'pirate'")
            assert curseur.rowcount == 0
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, using=ALIAS_APP):
        _sql(insertion, [uuid.uuid4(), "nouveau"])
        _refuse("DELETE FROM etablissement WHERE code = 'nouveau'", motif="permission denied")
        _refuse("TRUNCATE etablissement CASCADE", motif="permission denied")
    assert Etablissement.objects.filter(code="nouveau").exists()


# --- Le rôle applicatif ne peut ni contourner la RLS ni créer d'objet -----------------------------


@pytest.mark.parametrize(
    ("table", "politique"),
    [
        ("parametres_etablissement", "isolation_tenant"),
        ("note_test", "isolation_tenant"),
        ("etablissement", "lecture_etablissement"),
    ],
)
def test_alpha_app_ne_peut_pas_desactiver_la_rls(donnees, table, politique):
    _refuse(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY", motif="must be owner")
    _refuse(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY", motif="must be owner")
    _refuse(f"DROP POLICY {politique} ON {table}", motif="must be owner")
    _refuse(
        f"ALTER POLICY {politique} ON {table} USING (true)",
        motif="must be owner",
    )


def test_row_security_off_ne_contourne_pas(donnees):
    with transaction.atomic(using=ALIAS_APP):
        _sql("SET LOCAL row_security = off")
        _refuse("SELECT count(*) FROM note_test", motif="row-level security")


def test_alpha_app_ne_peut_pas_creer_de_table(donnees):
    _refuse("CREATE TABLE pirate (id int)", motif="permission denied")
    _refuse("CREATE TABLE public.pirate (id int)", motif="permission denied")
    _refuse("CREATE TEMPORARY TABLE pirate (id int)", motif="permission denied")
    _refuse("CREATE SCHEMA pirate", motif="permission denied")
    _refuse(
        "CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$",
        motif="permission denied",
    )


def test_extensions_utilisables_par_alpha_app():
    # citext et btree_gist sont créées avant la révocation de EXECUTE pour PUBLIC.
    assert _sql("SELECT 'Mamadou@Exemple.SN'::citext = 'mamadou@exemple.sn'::citext") == [(True,)]


# --- Correctif B1 : tables techniques de Django ------------------------------------------------


@pytest.mark.parametrize(
    "table",
    ["django_session", "django_content_type", "auth_permission", "auth_group"],
)
def test_droits_sur_les_tables_techniques(table):
    droits = _sql(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = %s AND table_name = %s",
        [settings.ALPHA_DB_APP_ROLE, table],
    )
    assert {d for (d,) in droits} == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    # Pas de RLS sur ces tables.
    assert _sql("SELECT relrowsecurity FROM pg_class WHERE relname = %s", [table]) == [(False,)]


def test_django_migrations_en_lecture_seule():
    assert _sql("SELECT count(*) > 0 FROM django_migrations") == [(True,)]
    _refuse(
        "INSERT INTO django_migrations (app, name, applied) VALUES ('x', 'y', now())",
        motif="permission denied",
    )


@override_settings(DATABASE_ROUTERS=["tests.conftest.RouteurApplicatif"])
def test_session_django_fonctionne_sous_alpha_app():
    """Création, relecture, modification et suppression d'une session par alpha_app."""
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    session = SessionStore()
    session["tenant_id"] = str(uuid.uuid4())
    session["scope"] = "tenant"
    session.save()
    cle = session.session_key

    assert _sql("SELECT count(*) FROM django_session WHERE session_key = %s", [cle]) == [(1,)]

    # Relecture et mise à jour directement en base (sans passer par le cache).
    StoreBase = import_module("django.contrib.sessions.backends.db").SessionStore
    relue = StoreBase(session_key=cle)
    assert relue["scope"] == "tenant"
    relue["scope"] = "platform"
    relue.save()
    assert StoreBase(session_key=cle).load()["scope"] == "platform"

    relue.delete()
    assert _sql("SELECT count(*) FROM django_session WHERE session_key = %s", [cle]) == [(0,)]
