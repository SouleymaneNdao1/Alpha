"""RLS des tables de la tâche B8 : tache, absence, delegation (§ 3.5)."""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, ProgrammingError, connection, transaction

from alpha.delegations.models import Absence, Delegation
from alpha.taches.models import Action, Module, Tache
from alpha.taches.services import ouvrir
from alpha.tenancy.contexte import contexte_tenant
from tests.outils_b8 import instant

pytestmark = pytest.mark.django_db

TABLES = ("tache", "absence", "delegation")


def _compter(table: str) -> int:
    with connection.cursor() as curseur:
        curseur.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608 - noms constants
        return curseur.fetchone()[0]


@pytest.fixture
def donnees_a(etab_a, utilisateur_a):
    from tests.fabriques import UtilisateurFactory

    autre = UtilisateurFactory(etablissement=etab_a, prenom="Cheikh", nom="Badiane")
    with contexte_tenant(etab_a.id):
        absence = Absence.objects.create(
            utilisateur=utilisateur_a,
            debut=instant("2030-03-11T00:00:00+00:00"),
            fin=instant("2030-03-16T00:00:00+00:00"),
            motif="CONGE",
        )
        Delegation.objects.create(
            absence=absence,
            delegant=utilisateur_a,
            delegataire=autre,
            debut=absence.debut,
            fin=absence.fin,
        )
        ouvrir(
            absence,
            module=Module.COMPTE,
            action=Action.VALIDER,
            titre="Absence",
            assigne_utilisateur=autre,
        )
    return absence


def test_sans_contexte_aucune_ligne(donnees_a):
    for table in TABLES:
        assert _compter(table) == 0, table


def test_contexte_a_voit_ses_lignes_contexte_b_aucune(donnees_a, etab_a, etab_b):
    with contexte_tenant(etab_a.id):
        assert [_compter(t) for t in TABLES] == [1, 1, 1]
    with contexte_tenant(etab_b.id):
        assert [_compter(t) for t in TABLES] == [0, 0, 0]
        assert not Tache.objects.exists()


def test_insertion_avec_l_etablissement_de_b_refusee(donnees_a, etab_a, etab_b):
    """Sous le contexte A, une ligne marquée B est refusée par la politique WITH CHECK."""
    with (
        contexte_tenant(etab_a.id),
        pytest.raises(ProgrammingError),
        transaction.atomic(),
        connection.cursor() as curseur,
    ):
        curseur.execute(
            "INSERT INTO tache (id, etablissement_id, module, source_type, source_id, "
            "reference, titre, sous_titre, devise, action, type_echeance, "
            "assigne_utilisateur_id, lien, statut, resultat, cree_le) "
            "SELECT %s, %s, 'COMPTE', 'tests.x', %s, '', 't', '', 'XOF', 'VALIDER', "
            "'AVANT', assigne_utilisateur_id, '', 'OUVERTE', '', now() FROM tache LIMIT 1",
            [str(uuid.uuid4()), str(etab_b.id), str(uuid.uuid4())],
        )


def test_reference_vers_un_utilisateur_de_b_refusee(donnees_a, etab_a, utilisateur_b):
    """Clé étrangère « même établissement » : une tâche de A ne vise pas un utilisateur de B."""
    with contexte_tenant(etab_a.id), pytest.raises(IntegrityError), transaction.atomic():
        ouvrir(
            ("tests.x", uuid.uuid4()),
            module=Module.COMPTE,
            action=Action.TRAITER,
            titre="t",
            assigne_utilisateur=utilisateur_b.pk,
        )
        with connection.cursor() as curseur:
            curseur.execute("SET CONSTRAINTS ALL IMMEDIATE")
