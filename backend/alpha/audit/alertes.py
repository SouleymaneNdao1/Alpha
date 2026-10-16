"""E-mails du journal d'audit : ancre quotidienne (P7) et alerte de rupture (§ 6.4, § 6.5).

Destinataires :
- adresse sécurité FYXOP : réglage de plateforme ``ALPHA_EMAIL_SECURITE_FYXOP``
  (variable d'environnement du même nom) ;
- contrôle interne / auditeur du client : ``ParametresEtablissement.email_controle_interne`` ;
- titulaires de ``audit.lecture`` (alerte de rupture, § 6.4, étape 5) : fournis
  par la fonction désignée par ``ALPHA_AUDIT_DESTINATAIRES_AUDIT_LECTURE`` (chemin
  pointé ``etablissement_id -> list[str]``), à brancher par B3 ; liste vide d'ici là.

Les messages sont préparés ici puis envoyés par la tâche Celery
``audit.envoyer_email`` (backend e-mail de Django), planifiée par
``transaction.on_commit`` : aucun e-mail pour une transaction annulée (§ 3.7).
Un message par destinataire : aucun destinataire ne voit l'adresse des autres.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.module_loading import import_string

from alpha.tenancy.models import Etablissement, ParametresEtablissement

journal = logging.getLogger("alpha.audit")


def email_securite_fyxop() -> str:
    return (getattr(settings, "ALPHA_EMAIL_SECURITE_FYXOP", "") or "").strip()


def email_controle_interne(etablissement_id: uuid.UUID | None) -> str:
    """Adresse du contrôle interne de l'établissement COURANT (lecture sous RLS)."""
    if etablissement_id is None:
        return ""
    parametres = ParametresEtablissement.objects.filter(etablissement_id=etablissement_id).first()
    return (parametres.email_controle_interne or "").strip() if parametres else ""


def destinataires_audit_lecture(etablissement_id: uuid.UUID | None) -> list[str]:
    chemin = getattr(settings, "ALPHA_AUDIT_DESTINATAIRES_AUDIT_LECTURE", None)
    if not chemin or etablissement_id is None:
        return []
    return list(import_string(chemin)(etablissement_id))


def libelle_chaine(etablissement_id: uuid.UUID | None) -> tuple[str, str]:
    """(raison sociale, code) de l'établissement, ou libellé de la chaîne plateforme."""
    if etablissement_id is None:
        return "Plateforme ALPHA (FYXOP)", "plateforme"
    etablissement = Etablissement.objects.filter(pk=etablissement_id).first()
    if etablissement is None:
        return str(etablissement_id), str(etablissement_id)
    return etablissement.raison_sociale, etablissement.code


def _uniques(adresses: list[str]) -> list[str]:
    vus: list[str] = []
    for adresse in adresses:
        if adresse and adresse.lower() not in {v.lower() for v in vus}:
            vus.append(adresse)
    return vus


def programmer_envoi(destinataires: list[str], sujet: str, corps: str) -> list[str]:
    """Planifie un e-mail par destinataire, APRÈS validation de la transaction courante."""
    from .tasks import envoyer_email  # import tardif : tasks importe ce module

    adresses = _uniques(destinataires)
    for adresse in adresses:
        transaction.on_commit(lambda a=adresse: envoyer_email.delay([a], sujet, corps), robust=True)
    if not adresses:
        journal.warning("Aucun destinataire pour l'e-mail d'audit « %s ».", sujet)
    return adresses


def _contexte_controle(controle: Any) -> dict[str, Any]:
    raison_sociale, code = libelle_chaine(controle.etablissement_id)
    return {
        "raison_sociale": raison_sociale,
        "code": code,
        "controle": controle,
        "lance_le": timezone.localtime(controle.lance_le),
        "url_frontend": settings.ALPHA_URL_FRONTEND,
    }


def programmer_ancre(controle: Any) -> list[str]:
    """Ancre quotidienne (P7) : dernier seq/hash vérifiés de la chaîne, aux deux destinataires."""
    ctx = _contexte_controle(controle)
    sujet = (
        f"[ALPHA] Ancre du journal d'audit — {ctx['raison_sociale']} — {ctx['lance_le']:%d/%m/%Y}"
    )
    corps = render_to_string("audit/email/ancre.txt", ctx)
    destinataires = [email_controle_interne(controle.etablissement_id), email_securite_fyxop()]
    return programmer_envoi(destinataires, sujet, corps)


def programmer_alerte_rupture(controle: Any) -> list[str]:
    """Alerte immédiate (§ 6.4, étape 5) : FYXOP sécurité + titulaires de audit.lecture."""
    ctx = _contexte_controle(controle)
    sujet = f"[ALPHA] ALERTE : journal d'audit rompu — {ctx['raison_sociale']}"
    corps = render_to_string("audit/email/rupture.txt", ctx)
    destinataires = [
        email_securite_fyxop(),
        *destinataires_audit_lecture(controle.etablissement_id),
    ]
    return programmer_envoi(destinataires, sujet, corps)
