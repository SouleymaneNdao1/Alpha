"""T2 · Isolation au niveau SQL, connexion applicative ``alpha_app`` (RLS réelle).

Pour CHAQUE table d'établissement du sprint 1 (déduite des modèles, puis recoupée avec la
base) : un contexte A ne lit, n'insère, ne met à jour ni ne supprime aucune ligne de B, et
sans contexte on ne voit rien. Les requêtes sont du SQL brut (pas d'ORM, pas de manager
filtrant) : seule la politique RLS fait barrage.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db import ProgrammingError, connection, transaction
from django.db.utils import DatabaseError

from alpha.tenancy.contexte import contexte_tenant
from tests.outils_t2 import semer

pytestmark = pytest.mark.django_db


def _tables_par_modele() -> list[str]:
    """Tables des modèles qui portent une clé ``etablissement`` (hors table ``etablissement``)."""
    tables = set()
    for modele in apps.get_models():
        if modele._meta.proxy or not modele._meta.managed:
            continue
        if any(f.name == "etablissement" for f in modele._meta.get_fields()):
            tables.add(modele._meta.db_table)
    return sorted(tables)


TABLES = _tables_par_modele()


def _tables_en_base() -> list[str]:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' AND c.column_name = 'etablissement_id' "
            "AND t.table_type = 'BASE TABLE' ORDER BY 1"
        )
        return [t for (t,) in curseur.fetchall()]


def _colonne_nullable(table: str) -> bool:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND column_name = 'etablissement_id'",
            [table],
        )
        return curseur.fetchone()[0] == "YES"


def _compter(table: str, ou: str = "true", params=()) -> int:
    with connection.cursor() as curseur:
        curseur.execute(f'SELECT count(*) FROM "{table}" WHERE {ou}', params)  # noqa: S608
        return curseur.fetchone()[0]


def _execute(requete: str, params=()) -> int:
    """Exécute dans un point de sauvegarde ; renvoie le nombre de lignes touchées."""
    with transaction.atomic(), connection.cursor() as curseur:
        curseur.execute(requete, params)
        return curseur.rowcount


def _colonnes_inserables(table: str) -> str:
    """Colonnes de la table hors identité « GENERATED ALWAYS » (id du journal d'audit)."""
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = %s AND is_identity = 'NO' ORDER BY ordinal_position",
            [table],
        )
        return ", ".join(f'"{c}"' for (c,) in curseur.fetchall())


@pytest.fixture
def deux(etab_a, etab_b):
    return semer(etab_a), semer(etab_b)


def _pour_chaque_table(controle) -> None:
    """Applique ``controle(table)`` à toutes les tables ; échoue en nommant chaque fautive.

    (Une graine complète coûte cher : une seule par test, boucle sur les tables.)
    """
    echecs = []
    for table in TABLES:
        try:
            controle(table)
        except AssertionError as exc:
            echecs.append(f"{table} : {exc}")
    assert not echecs, "\n".join(echecs)


# --- Garde-fous du test lui-même ---------------------------------------------------------------


def test_les_tables_des_modeles_sont_celles_de_la_base():
    """Une table d'établissement ajoutée sans modèle déclaré (ou l'inverse) fait échouer."""
    assert set(TABLES) == set(_tables_en_base())
    assert len(TABLES) >= 18  # le test ne doit pas passer « à vide »


def test_la_graine_couvre_toutes_les_tables(deux):
    """Chaque table d'établissement contient au moins une ligne de A et une de B."""
    a, b = deux
    manquantes = []
    for table in TABLES:
        for etab in (a.etab, b.etab):
            with contexte_tenant(etab.id):
                if _compter(table, "etablissement_id = %s", [etab.id]) == 0:
                    manquantes.append(f"{table}/{etab.code}")
    assert not manquantes, f"Tables sans ligne dans la graine (tests/outils_t2.py) : {manquantes}"


# --- Lecture ----------------------------------------------------------------------------------


def test_sans_contexte_aucune_ligne(deux):
    _pour_chaque_table(lambda t: _egal(_compter(t), 0))


def _egal(obtenu, attendu, quoi=""):
    assert obtenu == attendu, f"{quoi} obtenu {obtenu}, attendu {attendu}"


def test_lecture_croisee_impossible(deux):
    a, b = deux

    def controle(table):
        with contexte_tenant(a.etab.id):
            assert _compter(table) > 0
            _egal(_compter(table, "etablissement_id = %s", [b.etab.id]), 0, "lignes de B vues")
            _egal(_compter(table, "etablissement_id <> %s", [a.etab.id]), 0, "lignes d'autrui")
            if _colonne_nullable(table):
                # Les lignes « plateforme » (etablissement_id NULL) restent invisibles d'un tenant.
                _egal(_compter(table, "etablissement_id IS NULL"), 0, "lignes plateforme vues")
        with contexte_tenant(b.etab.id):
            _egal(_compter(table, "etablissement_id = %s", [a.etab.id]), 0, "lignes de A vues")

    _pour_chaque_table(controle)


def test_la_table_etablissement_ne_montre_que_le_sien(deux):
    a, b = deux
    with contexte_tenant(a.etab.id):
        assert _compter("etablissement") == 1
        assert _compter("etablissement", "id = %s", [b.etab.id]) == 0
    assert _compter("etablissement") == 0


# --- Écriture ---------------------------------------------------------------------------------


def test_mise_a_jour_des_lignes_de_b_impossible(deux):
    a, b = deux

    def controle(table):
        with contexte_tenant(a.etab.id):
            try:
                touchees = _execute(
                    f'UPDATE "{table}" SET etablissement_id = etablissement_id '  # noqa: S608
                    "WHERE etablissement_id = %s",
                    [b.etab.id],
                )
            except (ProgrammingError, DatabaseError) as exc:
                # Journal en ajout seul : pas de droit UPDATE du tout, refus franc.
                assert "permission denied" in str(exc), str(exc)
                touchees = 0
        _egal(touchees, 0, "lignes de B mises à jour")
        with contexte_tenant(b.etab.id):
            assert _compter(table) > 0

    _pour_chaque_table(controle)


def test_deplacer_une_ligne_de_a_vers_b_refuse(deux):
    """Réaffecter les lignes de A à B (fuite par écriture) est refusé par WITH CHECK."""
    a, b = deux

    def controle(table):
        with contexte_tenant(a.etab.id):
            avant = _compter(table)
            try:
                _execute(f'UPDATE "{table}" SET etablissement_id = %s', [b.etab.id])  # noqa: S608
            except (ProgrammingError, DatabaseError) as exc:
                assert "row-level security" in str(exc) or "permission denied" in str(exc), str(exc)
            else:
                raise AssertionError("déplacement vers B accepté")
            _egal(_compter(table, "etablissement_id = %s", [a.etab.id]), avant, "lignes de A")
        with contexte_tenant(b.etab.id):
            _egal(_compter(table, "etablissement_id = %s", [a.etab.id]), 0, "lignes de A chez B")

    _pour_chaque_table(controle)


def test_suppression_des_lignes_de_b_impossible(deux):
    a, b = deux

    def controle(table):
        with contexte_tenant(b.etab.id):
            avant_b = _compter(table)
        with contexte_tenant(a.etab.id):
            try:
                touchees = _execute(
                    f'DELETE FROM "{table}" WHERE etablissement_id = %s',  # noqa: S608
                    [b.etab.id],
                )
            except (ProgrammingError, DatabaseError) as exc:
                # Tables en ajout seul (journal) ou sans droit DELETE : refus franc, tout aussi bon.
                assert "permission denied" in str(exc) or "ajout seul" in str(exc), str(exc)
                touchees = 0
        _egal(touchees, 0, "lignes de B supprimées")
        with contexte_tenant(b.etab.id):
            _egal(_compter(table), avant_b, "lignes restantes de B")

    _pour_chaque_table(controle)


def test_insertion_pour_b_sous_le_contexte_de_a_refusee(deux):
    """Copie des lignes de A en changeant seulement leur établissement : refusée."""
    a, b = deux

    def controle(table):
        with contexte_tenant(a.etab.id):
            try:
                colonnes = _colonnes_inserables(table)
                _execute(
                    f'INSERT INTO "{table}" ({colonnes}) '  # noqa: S608
                    f'SELECT {colonnes} FROM (SELECT (jsonb_populate_record(NULL::"{table}", '
                    "to_jsonb(x) || jsonb_build_object('etablissement_id', %s::text))).* "
                    f'FROM "{table}" x) y',
                    [str(b.etab.id)],
                )
            except (ProgrammingError, DatabaseError) as exc:
                assert "row-level security" in str(exc), str(exc)
            else:
                raise AssertionError("insertion pour B acceptée")
        with contexte_tenant(b.etab.id):
            _egal(_compter(table, "etablissement_id = %s", [a.etab.id]), 0, "lignes de A chez B")

    _pour_chaque_table(controle)
