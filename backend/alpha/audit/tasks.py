"""Tâches Celery du journal d'audit (architecture § 3.7, § 6.4, § 6.5).

Planification (Celery beat, heure de Dakar, ``CELERY_BEAT_SCHEDULE``) :
- 02:00 ``audit.verifier_toutes_chaines`` : une sous-tâche par établissement
  (``audit.verifier_chaine``), plus la chaîne de la plateforme ;
- 02:30 ``audit.envoyer_ancres`` : une sous-tâche par établissement
  (``audit.envoyer_ancre``), plus la chaîne de la plateforme.

Les orchestrateurs ouvrent ``contexte_tenant(None, scope="worker")``, qui ne
donne accès qu'à la LISTE des établissements, puis délèguent : chaque
sous-tâche s'exécute sous le contexte de son établissement (``tache_tenant``).
"""

from __future__ import annotations

import smtplib
import uuid

from celery import shared_task
from django.core.mail import EmailMessage

from alpha.core import contexte
from alpha.tenancy.celery import tache_tenant
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement

from . import ancrage, verification
from .models import ControleIntegriteAudit, Declencheur, StatutControle


def _etablissements() -> list[str]:
    with contexte_tenant(None, scope=contexte.SCOPE_WORKER, utilisateur_id=None):
        return [str(i) for i in Etablissement.objects.order_by("code").values_list("id", flat=True)]


# --- Vérification (§ 6.4) ---------------------------------------------------------------------


@tache_tenant(name="audit.verifier_chaine")
def verifier_chaine(etablissement_id: str) -> str:
    """Vérifie la chaîne d'un établissement (sous son contexte) ; renvoie le statut."""
    controle = verification.verifier_chaine(uuid.UUID(str(etablissement_id)), Declencheur.PLANIFIE)
    return controle.statut


@tache_tenant(name="audit.executer_controle")
def executer_controle(etablissement_id: str, controle_id: str) -> str:
    """Exécute un contrôle MANUEL déjà créé par l'API (``POST /audit/controles``, B11)."""
    controle = ControleIntegriteAudit.objects.filter(
        pk=uuid.UUID(str(controle_id)), statut=StatutControle.EN_COURS
    ).first()
    if controle is None:  # déjà exécuté, ou hors de l'établissement (la RLS le masque)
        return "IGNORE"
    return verification.verifier_chaine(
        uuid.UUID(str(etablissement_id)), Declencheur.MANUEL, controle=controle
    ).statut


@shared_task(name="audit.verifier_chaine_plateforme")
def verifier_chaine_plateforme() -> str:
    return verification.lancer_verification(None, Declencheur.PLANIFIE).statut


@shared_task(name="audit.verifier_toutes_chaines")
def verifier_toutes_chaines() -> int:
    """02:00 : une sous-tâche par établissement, plus la chaîne de la plateforme."""
    identifiants = _etablissements()
    for etablissement_id in identifiants:
        verifier_chaine.delay(etablissement_id)
    verifier_chaine_plateforme.delay()
    return len(identifiants) + 1


# --- Ancrage (§ 6.5, P7) -----------------------------------------------------------------------


@tache_tenant(name="audit.envoyer_ancre")
def envoyer_ancre(etablissement_id: str) -> str:
    return ancrage.ancrer(uuid.UUID(str(etablissement_id))).statut


@shared_task(name="audit.envoyer_ancre_plateforme")
def envoyer_ancre_plateforme() -> str:
    return ancrage.ancrer_plateforme().statut


@shared_task(name="audit.envoyer_ancres")
def envoyer_ancres() -> int:
    """02:30 : ancre de chaque chaîne vers le contrôle interne et FYXOP sécurité."""
    identifiants = _etablissements()
    for etablissement_id in identifiants:
        envoyer_ancre.delay(etablissement_id)
    envoyer_ancre_plateforme.delay()
    return len(identifiants) + 1


# --- Envoi des e-mails --------------------------------------------------------------------------


@shared_task(
    name="audit.envoyer_email",
    queue="defaut",
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=6,
)
def envoyer_email(destinataires: list[str], sujet: str, corps: str) -> int:
    """Envoie un e-mail texte par le backend e-mail de Django (Mailpit en dev, SMTP ensuite)."""
    return EmailMessage(subject=sujet, body=corps, to=list(destinataires)).send()
