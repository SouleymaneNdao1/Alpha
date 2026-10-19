"""Tâches Celery des comptes (architecture § 3.7).

- ``comptes.envoyer_email`` (``alpha.comptes.emails``) : envoi générique texte + HTML ;
- ``comptes.envoyer_email_securite`` : conservée pour compatibilité (B5), délègue à
  l'envoi générique ;
- ``comptes.envoyer_invitation`` : e-mail d'invitation (§ 4.3), exécuté sous le
  contexte de l'établissement (``tache_tenant``) ; planifié après le commit par
  ``alpha.comptes.raccordements.envoyer_invitation``.

Le contenu ne contient jamais de secret, hormis le lien à usage unique de l'invitation.
"""

from __future__ import annotations

import datetime

from celery import shared_task
from django.utils.dateparse import parse_datetime

from alpha.tenancy.celery import tache_tenant

from . import emails
from .emails import envoyer_email  # noqa: F401 - enregistre la tâche « comptes.envoyer_email »


@shared_task(name="comptes.envoyer_email_securite", queue="defaut")
def envoyer_email_securite(destinataire: str, sujet: str, corps: str) -> None:
    emails.envoyer_email([destinataire], sujet, corps)


@tache_tenant(name="comptes.envoyer_invitation")
def envoyer_invitation(
    etablissement_id: str, utilisateur_id: str, jeton_clair: str, expire_le: str
) -> int:
    """E-mail « Activez votre compte ALPHA » (lien ``/activation?jeton=…``)."""
    from alpha.organisation.models import AffectationRole
    from alpha.tenancy.models import Etablissement

    from .models import StatutUtilisateur, Utilisateur

    utilisateur = Utilisateur.objects.filter(pk=utilisateur_id).first()
    if utilisateur is None or utilisateur.statut != StatutUtilisateur.INVITE:
        return 0
    etablissement = Etablissement.objects.filter(pk=etablissement_id).first()
    affectation = (
        AffectationRole.objects.actives()
        .filter(utilisateur_id=utilisateur.pk, principal=True)
        .select_related("role")
        .first()
    )
    echeance = parse_datetime(expire_le) if isinstance(expire_le, str) else expire_le
    return emails.envoyer_maintenant(
        "invitation",
        utilisateur.email,
        prenom=utilisateur.prenom,
        etablissement=etablissement.raison_sociale if etablissement else "",
        role=affectation.role.libelle if affectation else "",
        lien=emails.lien(f"/activation?jeton={jeton_clair}"),
        expire_le=emails.heure(echeance) if isinstance(echeance, datetime.datetime) else "",
    )
