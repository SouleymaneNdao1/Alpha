"""E-mails d'alerte de sécurité des comptes (architecture § 4.2 étapes 5, 9 et 12).

Gabarits en français (``alpha.comptes.emails``), sans aucun secret (ni code, ni
jeton, ni mot de passe). L'envoi est planifié après validation de la transaction
courante (``transaction.on_commit`` → Celery).
"""

from __future__ import annotations

import datetime

from . import emails
from .models import Utilisateur


def compte_verrouille(utilisateur: Utilisateur, jusqua: datetime.datetime | None) -> None:
    emails.programmer(
        "compte_verrouille",
        utilisateur.email,
        prenom=utilisateur.prenom,
        heure=emails.heure(),
        jusqua=emails.heure(jusqua),
        bloque_par_admin=utilisateur.bloque_par_admin,
    )


def code_secours_utilise(utilisateur: Utilisateur, restants: int) -> None:
    emails.programmer(
        "code_secours_utilise",
        utilisateur.email,
        prenom=utilisateur.prenom,
        heure=emails.heure(),
        restants=restants,
    )


def nouvelle_connexion(utilisateur: Utilisateur, appareil: str, ip: str | None) -> None:
    emails.programmer(
        "nouvelle_connexion",
        utilisateur.email,
        prenom=utilisateur.prenom,
        appareil=appareil,
        ip=ip or "inconnue",
        heure=emails.heure(),
    )
