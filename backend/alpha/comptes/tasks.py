"""Tâches Celery des comptes (architecture § 3.7).

``comptes.envoyer_email_securite`` : e-mail d'alerte de sécurité (compte verrouillé,
code de secours utilisé, nouvelle connexion). Planifiée par
``transaction.on_commit`` (``alpha.comptes.alertes``) : aucun e-mail pour une
transaction annulée. Les gabarits définitifs (HTML, FR) viendront avec B6 ; le
contenu ne contient jamais de secret.
"""

from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail


@shared_task(name="comptes.envoyer_email_securite", queue="defaut")
def envoyer_email_securite(destinataire: str, sujet: str, corps: str) -> None:
    send_mail(sujet, corps, settings.DEFAULT_FROM_EMAIL, [destinataire], fail_silently=False)
