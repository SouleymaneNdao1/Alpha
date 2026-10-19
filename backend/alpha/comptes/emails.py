"""E-mails des comptes : gabarits en français et envoi par Celery après le commit (§ 3.7, B6).

Chaque e-mail a un gabarit texte (``comptes/emails/<nom>.txt``) et un gabarit HTML
(``comptes/emails/<nom>.html``, qui étend ``base.html``) ; le sujet est dans
``SUJETS``. Deux façons d'envoyer :

- ``programmer(nom, destinataire, **contexte)`` : rendu immédiat (aucune requête en
  base), puis envoi planifié par ``transaction.on_commit`` → tâche Celery
  ``comptes.envoyer_email``. Aucun e-mail ne part pour une transaction annulée ;
- ``envoyer_maintenant(nom, destinataire, **contexte)`` : depuis une tâche Celery
  (déjà après le commit), envoi direct.

Les gabarits ne contiennent jamais de secret, à l'exception du lien à usage unique
(activation, réinitialisation, réenrôlement), qui n'existe que dans l'e-mail : il
n'est ni journalisé ni stocké en clair.
"""

from __future__ import annotations

import datetime
import smtplib
from typing import Any

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

#: Sujet de chaque gabarit (``str.format`` sur le contexte).
SUJETS: dict[str, str] = {
    "invitation": "Activez votre compte ALPHA",
    "reinitialisation_mdp": "Réinitialisation de votre mot de passe ALPHA",
    "mdp_modifie": "Votre mot de passe ALPHA a été modifié",
    "telephone_signale": "Signalement de téléphone perdu enregistré",
    "telephone_signale_admin": "Téléphone perdu · {nom_utilisateur}",
    "reenrolement": "Configurez votre nouvelle application d'authentification ALPHA",
    "telephone_retrouve": "Votre application d'authentification est réactivée",
    "mfa_reenrole": "Votre nouvelle application d'authentification est active",
    "reinitialisation_fyxop_admin": "Réinitialisation par FYXOP · {nom_utilisateur}",
    "compte_verrouille": "Votre compte ALPHA est verrouillé",
    "code_secours_utilise": "Un code de secours a été utilisé",
    "nouvelle_connexion": "Nouvelle connexion à votre compte ALPHA",
    "authenticator_change": "Votre application d'authentification ALPHA a été remplacée",
}


def heure(instant: datetime.datetime | None = None) -> str:
    """« 19/10/2026 à 14:05 » (heure de Dakar)."""
    return timezone.localtime(instant or timezone.now()).strftime("%d/%m/%Y à %H:%M")


def lien(chemin: str) -> str:
    """URL absolue du frontend (``ALPHA_URL_FRONTEND``)."""
    return f"{settings.ALPHA_URL_FRONTEND}{chemin}"


def rendre(nom: str, **contexte: Any) -> tuple[str, str, str]:
    """(sujet, texte, html) du gabarit ``nom``."""
    if nom not in SUJETS:
        raise ValueError(f"Gabarit d'e-mail inconnu : {nom!r}.")
    contexte.setdefault("url_frontend", settings.ALPHA_URL_FRONTEND)
    contexte.setdefault("lien_telephone_perdu", lien("/activation?onglet=telephone-perdu"))
    sujet = SUJETS[nom].format(**contexte)
    texte = render_to_string(f"comptes/emails/{nom}.txt", contexte)
    html = render_to_string(f"comptes/emails/{nom}.html", {**contexte, "sujet": sujet})
    return sujet, texte.strip() + "\n", html


@shared_task(
    name="comptes.envoyer_email",
    queue="defaut",
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=6,
)
def envoyer_email(destinataires: list[str], sujet: str, texte: str, html: str = "") -> int:
    """Envoi générique (texte + HTML) par le backend e-mail de Django (Mailpit en recette)."""
    message = EmailMultiAlternatives(
        subject=sujet,
        body=texte,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(destinataires),
    )
    if html:
        message.attach_alternative(html, "text/html")
    return message.send()


def programmer(nom: str, destinataire: str, **contexte: Any) -> None:
    """Rend le gabarit maintenant ; envoi planifié APRÈS le commit (un message par destinataire)."""
    sujet, texte, html = rendre(nom, **contexte)
    transaction.on_commit(
        lambda: envoyer_email.delay([destinataire], sujet, texte, html), robust=True
    )


def envoyer_maintenant(nom: str, destinataire: str, **contexte: Any) -> int:
    """Envoi direct (à appeler depuis une tâche Celery, donc déjà après le commit)."""
    sujet, texte, html = rendre(nom, **contexte)
    return envoyer_email([destinataire], sujet, texte, html)
