"""Journal d'audit au niveau SQL (B4, architecture § 6.3) : immutabilité, droits, RLS, concurrence.

Connexions (voir ``tests/bd.py``) : ``default`` = alpha_app (soumis à la RLS),
``proprietaire`` = alpha_owner (propriétaire, BYPASSRLS), utilisé ici pour vérifier ce
qui est réellement en base et que même le propriétaire est arrêté par les triggers.
Tests transactionnels : chaque connexion ne voit que ce que l'autre a validé.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.conf import settings
from django.db import DatabaseError, connections, transaction

from alpha.audit import canonique
from alpha.audit.models import (
    Categorie,
    ControleIntegriteAudit,
    EvenementAudit,
    JournalImmuable,
    StatutControle,
)
from alpha.audit.services import journaliser
from alpha.audit.verification import lancer_verification
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant

from .bd import ALIAS_APP, ALIAS_PROPRIETAIRE, BASES_PROPRIETAIRE

pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_PROPRIETAIRE)

_INSERTION_BRUTE = (
    "INSERT INTO evenement_audit (etablissement_id, horodatage, acteur_type, acteur_libelle, "
    "categorie, action, objet_type, objet_id, objet_libelle, detail, user_agent, "
    "payload_canonique, seq, hash_precedent, hash) "
    "VALUES (%s, now(), 'SYSTEME', 'test', 'SECURITE', 'test.brut', '', '', '', '', '', '{}', "
    "999, repeat('0', 64), repeat('0', 64))"
)


def _sql(alias: str, requete: str, params=None) -> list[tuple]:
    with connections[alias].cursor() as curseur:
        curseur.execute(requete, params or [])
        return curseur.fetchall() if curseur.description else []


def _refuse(alias: str, requete: str, params=None, *, motif: str) -> None:
    with pytest.raises(DatabaseError, match=motif), transaction.atomic(using=alias):
        _sql(alias, requete, params)


def _ecrire(etablissement_id, n: int = 1, alias: str = ALIAS_APP, **kwargs) -> list:
    """n événements dans la chaîne de l'établissement (ou de la plateforme si None)."""
    if etablissement_id is None:
        with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, using=alias):
            return [
                journaliser(f"test.evenement{i}", Categorie.SECURITE, using=alias, **kwargs)
                for i in range(n)
            ]
    with contexte_tenant(etablissement_id, using=alias):
        return [
            journaliser(f"test.evenement{i}", Categorie.MODIFICATION, using=alias, **kwargs)
            for i in range(n)
        ]


def _compter(alias: str, tenant=None, scope: str | None = None) -> int:
    """count(*) sur evenement_audit sous le contexte donné (aucun contexte par défaut)."""
    with transaction.atomic(using=alias):
        if scope is not None:
            _sql(
                alias,
                "SELECT set_config('app.current_tenant', %s, true), "
                "set_config('app.scope', %s, true)",
                [str(tenant) if tenant else "", scope],
            )
        return _sql(alias, "SELECT count(*) FROM evenement_audit")[0][0]


# --- Chaînage par le trigger -------------------------------------------------------------------


def test_le_trigger_fixe_seq_et_empreintes(etab_a):
    premier, second = _ecrire(etab_a.id, 2, alias=ALIAS_APP)
    assert (premier.seq, second.seq) == (1, 2)
    assert premier.hash_precedent == canonique.genese(etab_a.id)
    assert premier.hash == canonique.empreinte(premier.hash_precedent, 1, premier.payload_canonique)
    assert second.hash_precedent == premier.hash
    assert second.hash == canonique.empreinte(premier.hash, 2, second.payload_canonique)


def test_les_valeurs_fournies_par_l_appelant_sont_ecrasees(etab_a):
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        seq, hash_precedent = _sql(
            ALIAS_APP, _INSERTION_BRUTE + " RETURNING seq, hash_precedent", [str(etab_a.id)]
        )[0]
    assert seq == 1
    assert hash_precedent == canonique.genese(etab_a.id)


def test_chaines_independantes_par_etablissement_et_plateforme(etab_a, etab_b):
    _ecrire(etab_a.id, 3)
    _ecrire(etab_b.id, 2)
    _ecrire(None, 2)
    lignes = _sql(
        ALIAS_PROPRIETAIRE,
        "SELECT etablissement_id, max(seq), count(*) FROM evenement_audit GROUP BY 1",
    )
    assert {(e, m, n) for e, m, n in lignes} == {(etab_a.id, 3, 3), (etab_b.id, 2, 2), (None, 2, 2)}


def test_id_genere_toujours(etab_a):
    _refuse(
        ALIAS_PROPRIETAIRE,
        _INSERTION_BRUTE.replace("(etablissement_id,", "(id, etablissement_id,").replace(
            "VALUES (%s,", "VALUES (1, %s,"
        ),
        [str(etab_a.id)],
        motif="non-DEFAULT|GENERATED ALWAYS",
    )


# --- Immutabilité (§ 6.3) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "requete",
    [
        "UPDATE evenement_audit SET detail = 'falsifié'",
        "DELETE FROM evenement_audit",
        "TRUNCATE evenement_audit",
    ],
)
def test_role_applicatif_ne_peut_ni_modifier_ni_supprimer(etab_a, requete):
    _ecrire(etab_a.id, 2)
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        _refuse(ALIAS_APP, requete, motif="permission denied")
    assert _compter(ALIAS_PROPRIETAIRE) == 2


@pytest.mark.parametrize(
    ("requete", "operation"),
    [
        ("UPDATE evenement_audit SET detail = 'falsifié'", "UPDATE"),
        ("DELETE FROM evenement_audit", "DELETE"),
        ("TRUNCATE evenement_audit", "TRUNCATE"),
        ("TRUNCATE evenement_audit CASCADE", "TRUNCATE"),
    ],
)
def test_proprietaire_refuse_par_trigger(etab_a, requete, operation):
    """Même alpha_owner (propriétaire, BYPASSRLS) ne peut ni modifier ni supprimer."""
    _ecrire(etab_a.id, 2)
    _refuse(ALIAS_PROPRIETAIRE, requete, motif=f"ajout seul : {operation} interdit")
    assert _compter(ALIAS_PROPRIETAIRE) == 2


def test_droits_du_role_applicatif():
    droits = {
        p
        for (p,) in _sql(
            ALIAS_PROPRIETAIRE,
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'evenement_audit' AND grantee = %s",
            [settings.ALPHA_DB_APP_ROLE],
        )
    }
    assert droits == {"SELECT", "INSERT"}


def test_l_orm_refuse_modification_et_suppression(etab_a):
    (evenement,) = _ecrire(etab_a.id)
    with contexte_tenant(etab_a.id):
        with pytest.raises(JournalImmuable):
            EvenementAudit.objects.filter(pk=evenement.pk).update(detail="x")
        with pytest.raises(JournalImmuable):
            EvenementAudit.objects.filter(pk=evenement.pk).delete()
        with pytest.raises(JournalImmuable):
            EvenementAudit.objects.get(pk=evenement.pk).save()


# --- RLS (§ 6.3) ------------------------------------------------------------------------------


@pytest.fixture
def trois_chaines(etab_a, etab_b):
    _ecrire(etab_a.id, 3)
    _ecrire(etab_b.id, 2)
    _ecrire(None, 1)
    return etab_a, etab_b


def test_rls_activee_forcee_et_politiques_presentes():
    for table, attendues in (
        ("evenement_audit", {"audit_lecture", "audit_insertion"}),
        ("controle_integrite_audit", {"isolation_controle_audit"}),
    ):
        active, forcee = _sql(
            ALIAS_PROPRIETAIRE,
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
            [table],
        )[0]
        politiques = {
            p
            for (p,) in _sql(
                ALIAS_PROPRIETAIRE,
                "SELECT policyname FROM pg_policies WHERE tablename = %s",
                [table],
            )
        }
        assert (active, forcee) == (True, True)
        assert politiques == attendues


def test_rls_lecture_sans_contexte_zero_ligne(trois_chaines):
    assert _compter(ALIAS_PROPRIETAIRE) == 6  # propriétaire (BYPASSRLS) : tout
    assert _compter(ALIAS_APP) == 0  # rôle applicatif sans contexte : rien
    assert _compter(ALIAS_APP, None, contexte.SCOPE_ANONYMOUS) == 0
    assert _compter(ALIAS_APP, None, contexte.SCOPE_WORKER) == 0


def test_rls_lecture_pas_de_lecture_croisee(trois_chaines):
    etab_a, etab_b = trois_chaines
    for etab, attendu in ((etab_a, 3), (etab_b, 2)):
        with contexte_tenant(etab.id, using=ALIAS_APP):
            lignes = _sql(ALIAS_APP, "SELECT DISTINCT etablissement_id FROM evenement_audit")
            assert lignes == [(etab.id,)]
            assert _sql(ALIAS_APP, "SELECT count(*) FROM evenement_audit")[0][0] == attendu
            # Même par l'ORM, en demandant explicitement l'autre établissement.
            autre = etab_b if etab is etab_a else etab_a
            assert not EvenementAudit.objects.using(ALIAS_APP).filter(etablissement=autre).exists()


def test_rls_chaine_plateforme_reservee_a_la_portee_plateforme(trois_chaines):
    assert _compter(ALIAS_APP, None, contexte.SCOPE_PLATFORM) == 1
    etab_a, _ = trois_chaines
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        assert _sql(
            ALIAS_APP, "SELECT count(*) FROM evenement_audit WHERE etablissement_id IS NULL"
        ) == [(0,)]


def test_rls_insertion_dans_un_autre_etablissement_refusee(etab_a, etab_b):
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        _refuse(ALIAS_APP, _INSERTION_BRUTE, [str(etab_b.id)], motif="row-level security")
    # Sans contexte : seule la chaîne de la plateforme est accessible en écriture.
    _refuse(ALIAS_APP, _INSERTION_BRUTE, [str(etab_a.id)], motif="row-level security")
    assert _compter(ALIAS_PROPRIETAIRE) == 0


def test_rls_insertion_anonyme_dans_la_chaine_plateforme(etab_a):
    """Échec de connexion anonyme : écrit dans la chaîne plateforme sans pouvoir la lire."""
    with transaction.atomic(using=ALIAS_APP):
        evenement = journaliser("auth.connexion.echec", Categorie.CONNEXION, using=ALIAS_APP)
    assert evenement.etablissement_id is None
    assert evenement.seq is None  # pas de RETURNING : la ligne n'est pas lisible
    assert _compter(ALIAS_APP) == 0
    assert _sql(ALIAS_PROPRIETAIRE, "SELECT seq, action FROM evenement_audit") == [
        (1, "auth.connexion.echec")
    ]


def test_rls_controles_d_integrite(etab_a, etab_b):
    lancer_verification(etab_a.id)
    lancer_verification(etab_b.id)
    lancer_verification(None)
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        visibles = list(
            ControleIntegriteAudit.objects.using(ALIAS_APP).values_list(
                "etablissement_id", flat=True
            )
        )
        assert visibles == [etab_a.id]
        _refuse(ALIAS_APP, "DELETE FROM controle_integrite_audit", motif="permission denied")
    with transaction.atomic(using=ALIAS_APP):
        assert _sql(ALIAS_APP, "SELECT count(*) FROM controle_integrite_audit") == [(0,)]


# --- Concurrence (§ 6.2 : verrou consultatif par chaîne) ---------------------------------------


def _ecrire_en_parallele(etablissement_id, numero: int) -> None:
    try:
        with contexte_tenant(etablissement_id, using=ALIAS_APP):
            journaliser(f"test.concurrence.{numero}", Categorie.MODIFICATION, using=ALIAS_APP)
    finally:
        connections[ALIAS_APP].close()


def test_100_insertions_concurrentes_seq_contigus_et_chaine_valide(etab_a, etab_b):
    with ThreadPoolExecutor(max_workers=20) as executeur:
        travaux = [executeur.submit(_ecrire_en_parallele, etab_a.id, i) for i in range(100)]
        # En même temps, une autre chaîne : son verrou est distinct.
        travaux += [executeur.submit(_ecrire_en_parallele, etab_b.id, i) for i in range(20)]
        for travail in travaux:
            travail.result()

    seqs = [
        s
        for (s,) in _sql(
            ALIAS_PROPRIETAIRE,
            "SELECT seq FROM evenement_audit WHERE etablissement_id = %s ORDER BY seq",
            [str(etab_a.id)],
        )
    ]
    assert seqs == list(range(1, 101))
    actions = _sql(
        ALIAS_PROPRIETAIRE,
        "SELECT count(DISTINCT action) FROM evenement_audit WHERE etablissement_id = %s",
        [str(etab_a.id)],
    )
    assert actions == [(100,)]

    controle = lancer_verification(etab_a.id, using=ALIAS_APP)
    assert controle.statut == StatutControle.INTACTE, controle.message
    assert (controle.nb_evenements, controle.dernier_seq) == (100, 100)
    assert lancer_verification(etab_b.id, using=ALIAS_APP).dernier_seq == 20


def test_identifiant_de_chaine_plateforme():
    assert canonique.cle_chaine(None) == uuid.UUID(int=0)
