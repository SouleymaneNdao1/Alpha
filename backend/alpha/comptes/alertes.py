"""E-mails d'alerte de sécurité des comptes (architecture § 4.2 étapes 5, 9 et 12).

Textes en français, sans aucun secret (ni code, ni jeton, ni mot de passe).
L'envoi est planifié après validation de la transaction courante.
"""

from __future__ import annotations

import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Utilisateur


def _heure(instant: datetime.datetime | None = None) -> str:
    return timezone.localtime(instant or timezone.now()).strftime("%d/%m/%Y à %H:%M")


def _programmer(destinataire: str, sujet: str, corps: str) -> None:
    from .tasks import envoyer_email_securite

    transaction.on_commit(
        lambda: envoyer_email_securite.delay(destinataire, sujet, corps), robust=True
    )


def compte_verrouille(utilisateur: Utilisateur, jusqua: datetime.datetime | None) -> None:
    if utilisateur.bloque_par_admin:
        suite = (
            "Après plusieurs verrouillages successifs, seul un administrateur de votre "
            "établissement peut le débloquer."
        )
    else:
        suite = f"Il sera de nouveau accessible le {_heure(jusqua)}."
    corps = (
        f"Bonjour {utilisateur.prenom},\n\n"
        f"Votre compte ALPHA a été verrouillé le {_heure()} après plusieurs tentatives de "
        f"connexion échouées. {suite}\n\n"
        "Si vous n'êtes pas à l'origine de ces tentatives, prévenez votre administrateur.\n\n"
        "ALPHA"
    )
    _programmer(utilisateur.email, "Votre compte ALPHA est verrouillé", corps)


def code_secours_utilise(utilisateur: Utilisateur, restants: int) -> None:
    corps = (
        f"Bonjour {utilisateur.prenom},\n\n"
        f"Un code de secours a été utilisé pour vous connecter à ALPHA le {_heure()}. "
        f"Il vous reste {restants} code(s) de secours.\n\n"
        "Si vous n'êtes pas à l'origine de cette connexion, signalez-le immédiatement "
        f"depuis {settings.ALPHA_URL_FRONTEND}/activation?onglet=telephone-perdu.\n\n"
        "ALPHA"
    )
    _programmer(utilisateur.email, "Un code de secours a été utilisé", corps)


def nouvelle_connexion(utilisateur: Utilisateur, appareil: str, ip: str | None) -> None:
    corps = (
        f"Bonjour {utilisateur.prenom},\n\n"
        "Une connexion à votre compte ALPHA a eu lieu depuis un appareil ou un lieu "
        "inhabituel :\n"
        f"  - appareil : {appareil}\n"
        f"  - adresse IP : {ip or 'inconnue'}\n"
        f"  - heure : {_heure()}\n\n"
        "Si c'était bien vous, aucune action n'est nécessaire. Sinon : « Ce n'était pas moi » "
        f"{settings.ALPHA_URL_FRONTEND}/activation?onglet=telephone-perdu\n\n"
        "ALPHA"
    )
    _programmer(utilisateur.email, "Nouvelle connexion à votre compte ALPHA", corps)
