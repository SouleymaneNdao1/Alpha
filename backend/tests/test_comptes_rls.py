"""RLS des tables de comptes et d'organisation, en alpha_app (tâche B3).

Critère de fin de B3 : « migrations + RLS + test de couverture RLS vert ».
Vérifie, au niveau SQL et sous le rôle applicatif (NOBYPASSRLS) :
- 0 ligne sans contexte sur chaque nouvelle table ;
- aucune lecture croisée entre les établissements A et B, ni écriture avec l'id de B ;
- la portée « platform » ne voit que les super-admins (et leurs propres jetons) ;
- ``alpha_resoudre_connexion`` / ``alpha_resoudre_jeton`` : seules colonnes prévues,
  exécutables par alpha_app mais pas par PUBLIC, SECURITY DEFINER d'alpha_owner.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from alpha.comptes.models import JetonUsageUnique, Utilisateur
from alpha.comptes.resolution import resoudre_connexion, resoudre_jeton
from alpha.core import contexte
from alpha.organisation.models import AffectationRole, Role, UniteOrganisationnelle
from alpha.organisation.roles_defaut import semer_roles_par_defaut
from alpha.tenancy.contexte import contexte_tenant

from .conftest import ALIAS_APP, BASES_APP
from .outils_comptes import creer_jeton, creer_super_admin, creer_utilisateur

pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_APP)

TABLES_B3 = (
    "utilisateur",
    "jeton_usage_unique",
    "unite_organisationnelle",
    "role",
    "affectation_role",
)
POLITIQUES_ATTENDUES = {
    "utilisateur": "isolation_utilisateur",
    "jeton_usage_unique": "isolation_tenant_ou_plateforme",
    "unite_organisationnelle": "isolation_tenant",
    "role": "isolation_tenant",
    "affectation_role": "isolation_tenant",
}


def _sql(requete: str, params=None) -> list[tuple]:
    with connections[ALIAS_APP].cursor() as curseur:
        curseur.execute(requete, params or [])
        return curseur.fetchall() if curseur.description else []


def _compter(table: str) -> int:
    return _sql(f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - noms de table fixes


def _contexte_app(etablissement_id, scope=contexte.SCOPE_TENANT, utilisateur_id=None):
    return contexte_tenant(etablissement_id, scope, utilisateur_id=utilisateur_id, using=ALIAS_APP)


@pytest.fixture
def jeu(etab_a, etab_b):
    """Pour A et B : 2 utilisateurs, 1 jeton, rôles par défaut, 1 unité, 1 affectation."""
    donnees = {}
    for etab in (etab_a, etab_b):
        u1 = creer_utilisateur(etab, f"u1@{etab.code}.test")
        creer_utilisateur(etab, f"u2@{etab.code}.test")
        clair, jeton = creer_jeton(u1)
        with contexte_tenant(etab.id):
            semer_roles_par_defaut(etab)
            unite = UniteOrganisationnelle.objects.create(
                type="AGENCE", code="agence-1", libelle="Agence 1"
            )
            role = Role.objects.get(code="collaborateur")
            affectation = AffectationRole.objects.create(
                utilisateur=u1, role=role, unite=unite, principal=True
            )
        donnees[etab.code] = {
            "etab": etab,
            "u1": u1,
            "jeton": jeton,
            "clair": clair,
            "unite": unite,
            "role": role,
            "affectation": affectation,
        }
    sa = creer_super_admin()
    clair_sa, jeton_sa = creer_jeton(sa)
    donnees["plateforme"] = {"sa": sa, "jeton": jeton_sa, "clair": clair_sa}
    return donnees


# --- Structure ------------------------------------------------------------------------------


def test_rls_activee_forcee_avec_la_bonne_politique():
    for table, politique in POLITIQUES_ATTENDUES.items():
        ligne = _sql(
            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "WHERE c.relname = %s AND c.relnamespace = 'public'::regnamespace",
            [table],
        )
        assert ligne == [(True, True)], table
        politiques = _sql(
            "SELECT policyname, cmd FROM pg_policies WHERE tablename = %s AND %s = ANY(roles)",
            [table, settings.ALPHA_DB_APP_ROLE],
        )
        assert politiques == [(politique, "ALL")], table


# --- Sans contexte ---------------------------------------------------------------------------


def test_zero_ligne_sans_contexte(jeu):
    with transaction.atomic(using=ALIAS_APP):
        for table in TABLES_B3:
            assert _compter(table) == 0, table


def test_zero_ligne_en_portee_worker_ou_anonyme(jeu):
    for scope in (contexte.SCOPE_WORKER, contexte.SCOPE_ANONYMOUS):
        with _contexte_app(None, scope):
            for table in TABLES_B3:
                assert _compter(table) == 0, (scope, table)


# --- Isolation A / B -----------------------------------------------------------------------


def test_pas_de_lecture_croisee(jeu):
    a, b = jeu["banque-a"], jeu["sfd-b"]
    attendus = {
        "utilisateur": 2,
        "jeton_usage_unique": 1,
        "unite_organisationnelle": 1,
        "role": 16,
        "affectation_role": 1,
    }
    for courant, autre in ((a, b), (b, a)):
        with _contexte_app(courant["etab"].id):
            for table, nombre in attendus.items():
                assert _compter(table) == nombre, table
                assert (
                    _sql(
                        f"SELECT count(*) FROM {table} WHERE etablissement_id = %s",  # noqa: S608
                        [autre["etab"].id],
                    )[0][0]
                    == 0
                ), table
            # Accès direct par identifiant : rien.
            assert _sql("SELECT 1 FROM utilisateur WHERE id = %s", [autre["u1"].id]) == []
            assert _sql("SELECT 1 FROM role WHERE id = %s", [autre["role"].id]) == []
            # Le super-admin n'est pas visible depuis un établissement.
            assert _sql("SELECT 1 FROM utilisateur WHERE est_super_admin") == []


def test_orm_applicatif_ne_voit_que_son_etablissement(jeu):
    a = jeu["banque-a"]
    with _contexte_app(a["etab"].id):
        emails = set(Utilisateur.objects.using(ALIAS_APP).values_list("email", flat=True))
        assert emails == {"u1@banque-a.test", "u2@banque-a.test"}
        # Même le manager non filtré ne voit que l'établissement courant (RLS).
        assert Utilisateur.objets_globaux.using(ALIAS_APP).count() == 2
        assert JetonUsageUnique.objets_globaux.using(ALIAS_APP).count() == 1


def test_ecriture_pour_un_autre_etablissement_refusee(jeu):
    a, b = jeu["banque-a"], jeu["sfd-b"]
    with _contexte_app(a["etab"].id):
        for requete, params in (
            (
                "INSERT INTO role (id, etablissement_id, code, libelle, description, permissions,"
                " est_systeme, actif, ordre, cree_le, modifie_le) VALUES"
                " (%s, %s, 'x', 'X', '', '{}', false, true, 0, now(), now())",
                [uuid.uuid4(), b["etab"].id],
            ),
            (
                "INSERT INTO unite_organisationnelle (id, etablissement_id, type, code,"
                " libelle, actif, cree_le, modifie_le)"
                " VALUES (%s, %s, 'AGENCE', 'x', 'X', true, now(), now())",
                [uuid.uuid4(), b["etab"].id],
            ),
            (
                "UPDATE utilisateur SET etablissement_id = %s WHERE id = %s",
                [b["etab"].id, a["u1"].id],
            ),
        ):
            with (
                pytest.raises(DatabaseError, match="row-level security"),
                transaction.atomic(using=ALIAS_APP),
            ):
                _sql(requete, params)
        # UPDATE / DELETE d'une ligne de B : 0 ligne touchée.
        with connections[ALIAS_APP].cursor() as curseur:
            curseur.execute("UPDATE utilisateur SET nom = 'X' WHERE id = %s", [b["u1"].id])
            assert curseur.rowcount == 0
            curseur.execute("DELETE FROM affectation_role WHERE id = %s", [b["affectation"].id])
            assert curseur.rowcount == 0


def test_reference_vers_un_autre_etablissement_refusee(jeu):
    """Les contrôles de clé étrangère ignorent la RLS : la clé « même établissement » complète."""
    a, b = jeu["banque-a"], jeu["sfd-b"]
    with _contexte_app(a["etab"].id):
        for colonne, valeur in (
            ("role_id", b["role"].id),
            ("utilisateur_id", b["u1"].id),
            ("unite_id", b["unite"].id),
        ):
            valeurs = {
                "role_id": a["role"].id,
                "utilisateur_id": jeu["banque-a"]["u1"].id,
                "unite_id": None,
                colonne: valeur,
            }
            with (
                pytest.raises(DatabaseError, match="meme_etab"),
                transaction.atomic(using=ALIAS_APP),
            ):
                _sql(
                    "INSERT INTO affectation_role (id, etablissement_id, utilisateur_id, role_id,"
                    " unite_id, principal, debut, cree_le) VALUES"
                    " (%s, %s, %s, %s, %s, false, current_date, now())",
                    [
                        uuid.uuid4(),
                        a["etab"].id,
                        valeurs["utilisateur_id"],
                        valeurs["role_id"],
                        valeurs["unite_id"],
                    ],
                )
                _sql("SET CONSTRAINTS ALL IMMEDIATE")


# --- Portée plateforme ----------------------------------------------------------------------


def test_portee_plateforme(jeu):
    sa = jeu["plateforme"]["sa"]
    with _contexte_app(None, contexte.SCOPE_PLATFORM, utilisateur_id=sa.id):
        assert _sql("SELECT id FROM utilisateur") == [(sa.id,)]
        assert _sql("SELECT id FROM jeton_usage_unique") == [(jeu["plateforme"]["jeton"].id,)]
        for table in ("unite_organisationnelle", "role", "affectation_role"):
            assert _compter(table) == 0, table
    # Un autre utilisateur plateforme ne voit pas les jetons du super-admin.
    with _contexte_app(None, contexte.SCOPE_PLATFORM, utilisateur_id=uuid.uuid4()):
        assert _compter("jeton_usage_unique") == 0


# --- Fonctions SECURITY DEFINER -----------------------------------------------------------


def test_resoudre_connexion_sans_contexte_en_alpha_app(jeu):
    a, sa = jeu["banque-a"], jeu["plateforme"]["sa"]
    with transaction.atomic(using=ALIAS_APP):
        assert _compter("utilisateur") == 0  # la table reste invisible…
        res = resoudre_connexion("U1@Banque-A.test", using=ALIAS_APP)  # … mais l'e-mail se résout
        assert res == (a["u1"].id, a["etab"].id, False)
        assert resoudre_connexion("admin@FYXOP.test", using=ALIAS_APP) == (sa.id, None, True)
        assert resoudre_connexion("inconnu@banque-a.test", using=ALIAS_APP) is None


def test_resoudre_connexion_n_expose_que_les_colonnes_prevues(jeu):
    with connections[ALIAS_APP].cursor() as curseur:
        curseur.execute("SELECT * FROM alpha_resoudre_connexion(%s)", ["u1@banque-a.test"])
        assert [c.name for c in curseur.description] == [
            "utilisateur_id",
            "etablissement_id",
            "est_super_admin",
        ]
        curseur.execute("SELECT * FROM alpha_resoudre_jeton(%s)", ["0" * 64])
        assert [c.name for c in curseur.description] == [
            "jeton_id",
            "etablissement_id",
            "utilisateur_id",
            "objet",
        ]


def test_resoudre_jeton(jeu):
    a, b = jeu["banque-a"], jeu["sfd-b"]
    with transaction.atomic(using=ALIAS_APP):
        assert resoudre_jeton(a["clair"], using=ALIAS_APP) == (
            a["jeton"].id,
            a["etab"].id,
            a["u1"].id,
            "INVITATION",
        )
        assert resoudre_jeton(b["clair"], using=ALIAS_APP).etablissement_id == b["etab"].id
        assert resoudre_jeton(jeu["plateforme"]["clair"], using=ALIAS_APP).etablissement_id is None
        assert resoudre_jeton("jeton-inconnu", using=ALIAS_APP) is None


def test_resoudre_jeton_ignore_utilise_annule_expire(jeu):
    u = jeu["banque-a"]["u1"]
    clair_expire, _ = creer_jeton(u, objet="REINIT_MDP", expire_dans=datetime.timedelta(minutes=-1))
    clair_utilise, _ = creer_jeton(u, objet="REINIT_MDP", utilise_le=timezone.now())
    clair_annule, _ = creer_jeton(u, objet="REINIT_MDP", annule_le=timezone.now())
    with transaction.atomic(using=ALIAS_APP):
        for clair in (clair_expire, clair_utilise, clair_annule):
            assert resoudre_jeton(clair, using=ALIAS_APP) is None


def test_fonctions_security_definer_et_droits():
    lignes = _sql(
        "SELECT p.proname, p.prosecdef, pg_get_userbyid(p.proowner), p.proconfig,"
        " has_function_privilege(%s, p.oid, 'EXECUTE'),"
        " has_function_privilege('public', p.oid, 'EXECUTE')"
        " FROM pg_proc p WHERE p.proname IN ('alpha_resoudre_connexion', 'alpha_resoudre_jeton')"
        " ORDER BY 1",
        [settings.ALPHA_DB_APP_ROLE],
    )
    assert [ligne[0] for ligne in lignes] == ["alpha_resoudre_connexion", "alpha_resoudre_jeton"]
    for _nom, secdef, proprietaire, config, exec_app, exec_public in lignes:
        assert secdef is True
        assert proprietaire == "alpha_owner"
        assert config == ["search_path=public, pg_temp"]
        assert exec_app is True
        assert exec_public is False
