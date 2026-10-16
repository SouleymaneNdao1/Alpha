"""Vérification des chaînes, détection d'altération, commande et ancrage (B4, § 6.4, § 6.5, P7).

Les altérations sont faites comme le ferait un administrateur de la base : par la
connexion propriétaire, trigger d'immutabilité désactivé le temps de l'opération.
"""

from __future__ import annotations

import io

import pytest
from celery.schedules import crontab
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import override_settings

from alpha.audit import canonique, tasks
from alpha.audit.models import (
    Categorie,
    ControleIntegriteAudit,
    Declencheur,
    EvenementAudit,
    StatutControle,
)
from alpha.audit.services import journaliser
from alpha.audit.verification import ACTION_RUPTURE, lancer_verification
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import ParametresEtablissement
from config.celery import app as application_celery

from .conftest import ALIAS_APP, BASES_APP

pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_APP)

FYXOP = "securite@fyxop.test"
AUDITEUR_A = "controle.interne@banque-a.test"


def _ecrire(etablissement_id, n: int) -> None:
    with contexte_tenant(etablissement_id):
        for i in range(n):
            journaliser(
                f"test.evenement{i}", Categorie.MODIFICATION, detail=f"détail {i}", apres={"n": i}
            )


def _alterer(requete: str, params=None) -> None:
    """Modification « hors application » : trigger désactivé par le propriétaire."""
    with transaction.atomic(), connection.cursor() as curseur:
        curseur.execute("ALTER TABLE evenement_audit DISABLE TRIGGER evenement_audit_sans_maj")
        curseur.execute(requete, params or [])
        curseur.execute("ALTER TABLE evenement_audit ENABLE TRIGGER evenement_audit_sans_maj")


def _verifier(etablissement_id) -> ControleIntegriteAudit:
    """Vérification sous le rôle applicatif (RLS), comme en production."""
    return lancer_verification(etablissement_id, Declencheur.MANUEL, using=ALIAS_APP)


def _evenement(etab, seq) -> EvenementAudit:
    return EvenementAudit.objects.get(etablissement=etab, seq=seq)


@pytest.fixture
def chaine_a(etab_a):
    _ecrire(etab_a.id, 5)
    return etab_a


# --- Chaîne intacte ------------------------------------------------------------------------------


def test_chaine_intacte_et_ancre(chaine_a):
    controle = _verifier(chaine_a.id)
    assert controle.statut == StatutControle.INTACTE, controle.message
    assert (controle.nb_evenements, controle.dernier_seq) == (5, 5)
    assert controle.dernier_hash == _evenement(chaine_a, 5).hash
    assert controle.premier_seq_invalide is None
    assert controle.termine_le is not None


def test_chaine_vide_intacte(etab_b):
    controle = _verifier(etab_b.id)
    assert (controle.statut, controle.nb_evenements, controle.dernier_seq) == ("INTACTE", 0, None)


def test_verification_depuis_un_rang(chaine_a):
    controle = lancer_verification(chaine_a.id, depuis_seq=4, using=ALIAS_APP)
    assert (controle.statut, controle.nb_evenements, controle.dernier_seq) == ("INTACTE", 2, 5)


def test_chaine_plateforme(db):
    for _ in range(3):
        journaliser("auth.connexion.echec", Categorie.CONNEXION)
    controle = _verifier(None)
    assert (controle.statut, controle.dernier_seq, controle.etablissement_id) == (
        "INTACTE",
        3,
        None,
    )


# --- Altérations détectées ----------------------------------------------------------------------


def test_alteration_d_une_colonne_detectee(chaine_a):
    _alterer(
        "UPDATE evenement_audit SET detail = 'falsifié' WHERE etablissement_id = %s AND seq = 3",
        [str(chaine_a.id)],
    )
    controle = _verifier(chaine_a.id)
    assert controle.statut == StatutControle.ROMPUE
    assert controle.premier_seq_invalide == 3
    assert "colonne" in controle.message
    assert controle.dernier_seq == 2  # dernier événement valide


def test_alteration_d_une_valeur_json_detectee(chaine_a):
    _alterer(
        "UPDATE evenement_audit SET apres = '{\"n\": 99}' WHERE etablissement_id = %s AND seq = 2",
        [str(chaine_a.id)],
    )
    controle = _verifier(chaine_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 2)


def test_alteration_du_payload_seul_detectee(chaine_a):
    evenement = _evenement(chaine_a, 2)
    _alterer(
        "UPDATE evenement_audit SET payload_canonique = %s WHERE id = %s",
        [evenement.payload_canonique.replace("détail 1", "détail X"), evenement.id],
    )
    controle = _verifier(chaine_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 2)


def test_alteration_coherente_colonne_et_payload_detectee_par_l_empreinte(chaine_a):
    """Colonne ET payload modifiés de façon cohérente : seule l'empreinte trahit la fraude."""
    evenement = _evenement(chaine_a, 2)
    _alterer(
        "UPDATE evenement_audit SET detail = 'détail X', payload_canonique = %s WHERE id = %s",
        [evenement.payload_canonique.replace("détail 1", "détail X"), evenement.id],
    )
    controle = _verifier(chaine_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 2)
    assert "empreinte recalculée" in controle.message


def test_falsification_recalculee_du_dernier_evenement_detectee_par_l_ancre(chaine_a):
    """Dernier événement réécrit avec une empreinte recalculée : la chaîne paraît valide,
    mais l'ancre (contrôle précédent) ne correspond plus."""
    assert _verifier(chaine_a.id).statut == StatutControle.INTACTE
    evenement = _evenement(chaine_a, 5)
    payload = evenement.payload_canonique.replace("détail 4", "détail X")
    _alterer(
        "UPDATE evenement_audit SET detail = 'détail X', payload_canonique = %s, hash = %s "
        "WHERE id = %s",
        [payload, canonique.empreinte(evenement.hash_precedent, 5, payload), evenement.id],
    )
    controle = _verifier(chaine_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 5)
    assert "ancre" in controle.message


def test_suppression_au_milieu_detectee(chaine_a):
    _alterer(
        "DELETE FROM evenement_audit WHERE etablissement_id = %s AND seq = 3", [str(chaine_a.id)]
    )
    controle = _verifier(chaine_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 3)
    assert "manquant" in controle.message


def test_suppression_en_fin_de_chaine_detectee_par_l_ancre(chaine_a):
    assert _verifier(chaine_a.id).statut == StatutControle.INTACTE  # ancre : seq 5
    _alterer(
        "DELETE FROM evenement_audit WHERE etablissement_id = %s AND seq >= 4", [str(chaine_a.id)]
    )
    controle = _verifier(chaine_a.id)
    assert controle.statut == StatutControle.ROMPUE
    assert controle.premier_seq_invalide == 4
    assert "troncature" in controle.message
    # Le contrôle suivant reste ROMPU : l'ancre de référence est la dernière INTACTE.
    assert _verifier(chaine_a.id).statut == StatutControle.ROMPUE


def test_rupture_journalisee_et_alerte_envoyee(chaine_a):
    _alterer(
        "UPDATE evenement_audit SET detail = 'x' WHERE etablissement_id = %s AND seq = 1",
        [str(chaine_a.id)],
    )
    mail.outbox.clear()
    controle = _verifier(chaine_a.id)
    assert controle.statut == StatutControle.ROMPUE
    alerte = EvenementAudit.objects.get(etablissement=chaine_a, action=ACTION_RUPTURE)
    assert (alerte.categorie, alerte.acteur_type) == (Categorie.SECURITE, "SYSTEME")
    assert alerte.objet_id == str(controle.id)
    assert [m.to for m in mail.outbox] == [[FYXOP]]
    assert "ALERTE" in mail.outbox[0].subject
    assert "seq) : 1" in mail.outbox[0].body


def test_erreur_technique_enregistree(chaine_a, monkeypatch):
    from alpha.audit import verification

    def panne(*args, **kwargs):
        raise RuntimeError("panne")

    monkeypatch.setattr(verification, "_parcourir", panne)
    controle = _verifier(chaine_a.id)
    assert controle.statut == StatutControle.ERREUR
    assert ControleIntegriteAudit.objects.get(pk=controle.pk).statut == "ERREUR"


# --- Commande verifier_chaine_audit -------------------------------------------------------------


def test_commande_tous(chaine_a, etab_b):
    sortie = io.StringIO()
    call_command("verifier_chaine_audit", "--tous", stdout=sortie)
    texte = sortie.getvalue()
    assert "banque-a : INTACTE — 5 événement(s)" in texte
    assert "sfd-b : INTACTE" in texte
    assert "plateforme : INTACTE" in texte
    assert set(ControleIntegriteAudit.objects.values_list("declencheur", flat=True)) == {"MANUEL"}


def test_commande_code_de_sortie_2_si_rompue(chaine_a):
    call_command("verifier_chaine_audit", "--etablissement", "banque-a", stdout=io.StringIO())
    _alterer(
        "DELETE FROM evenement_audit WHERE etablissement_id = %s AND seq = 5", [str(chaine_a.id)]
    )
    with pytest.raises(CommandError) as erreur:
        call_command(
            "verifier_chaine_audit",
            "--etablissement",
            "banque-a",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert erreur.value.returncode == 2


def test_commande_etablissement_inconnu(db):
    with pytest.raises(CommandError, match="inconnu"):
        call_command("verifier_chaine_audit", "--etablissement", "absent")


# --- Tâches planifiées et ancrage (§ 6.5, P7) ----------------------------------------------------


def test_planification_celery_beat():
    planning = settings.CELERY_BEAT_SCHEDULE
    attendu = {
        "audit.verifier_toutes_chaines": crontab(hour=2, minute=0),
        "audit.envoyer_ancres": crontab(hour=2, minute=30),
    }
    assert {e["task"]: e["schedule"] for e in planning.values() if e["task"] in attendu} == attendu
    assert settings.CELERY_TIMEZONE == "Africa/Dakar"
    for nom in (*attendu, "audit.verifier_chaine", "audit.envoyer_ancre", "audit.envoyer_email"):
        assert nom in application_celery.tasks


@pytest.fixture
def auditeur_a(etab_a):
    with contexte_tenant(etab_a.id):
        ParametresEtablissement.objects.update(email_controle_interne=AUDITEUR_A)
    return etab_a


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_ancrage_enregistre_un_controle_et_prepare_les_emails(auditeur_a, etab_b):
    _ecrire(auditeur_a.id, 3)
    journaliser("auth.connexion.echec", Categorie.CONNEXION)  # chaîne plateforme
    mail.outbox.clear()

    tasks.envoyer_ancres.delay()

    controle_a = ControleIntegriteAudit.objects.get(etablissement=auditeur_a)
    assert (controle_a.statut, controle_a.declencheur, controle_a.dernier_seq) == (
        "INTACTE",
        "PLANIFIE",
        3,
    )
    assert ControleIntegriteAudit.objects.filter(etablissement=etab_b).count() == 1
    assert ControleIntegriteAudit.objects.filter(etablissement__isnull=True).count() == 1

    par_destinataire: dict[str, list] = {}
    for message in mail.outbox:
        assert len(message.to) == 1  # un message par destinataire
        par_destinataire.setdefault(message.to[0], []).append(message)
    # Contrôle interne de A : sa seule chaîne ; FYXOP : A, B et la plateforme.
    assert len(par_destinataire[AUDITEUR_A]) == 1
    assert len(par_destinataire[FYXOP]) == 3
    ancre_a = par_destinataire[AUDITEUR_A][0]
    assert "Ancre du journal d'audit" in ancre_a.subject
    assert "Établissement banque-a" in ancre_a.subject
    assert controle_a.dernier_hash in ancre_a.body
    assert "Dernier rang (seq) : 3" in ancre_a.body
    assert "&#x27;" not in ancre_a.body  # texte brut, pas d'échappement HTML


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_ancrage_reutilise_le_controle_de_la_nuit(auditeur_a):
    _ecrire(auditeur_a.id, 2)
    tasks.verifier_toutes_chaines.delay()  # 02:00
    assert ControleIntegriteAudit.objects.filter(etablissement=auditeur_a).count() == 1
    mail.outbox.clear()
    tasks.envoyer_ancre.delay(str(auditeur_a.id))  # 02:30
    assert ControleIntegriteAudit.objects.filter(etablissement=auditeur_a).count() == 1
    assert sorted(m.to[0] for m in mail.outbox) == sorted([AUDITEUR_A, FYXOP])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_pas_d_ancre_pour_une_chaine_rompue(auditeur_a):
    _ecrire(auditeur_a.id, 2)
    _alterer(
        "UPDATE evenement_audit SET detail = 'x' WHERE etablissement_id = %s AND seq = 2",
        [str(auditeur_a.id)],
    )
    mail.outbox.clear()
    tasks.envoyer_ancre.delay(str(auditeur_a.id))
    assert [m.subject.startswith("[ALPHA] ALERTE") for m in mail.outbox] == [True]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_aucun_email_si_la_transaction_est_annulee(auditeur_a):
    from alpha.audit import ancrage

    mail.outbox.clear()
    with pytest.raises(RuntimeError), contexte_tenant(auditeur_a.id):
        ancrage.ancrer(auditeur_a.id)
        raise RuntimeError("annulation")
    assert mail.outbox == []
    assert not ControleIntegriteAudit.objects.exists()
