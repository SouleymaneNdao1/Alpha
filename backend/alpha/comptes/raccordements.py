"""Points de raccordement de l'administration (B7) vers les tâches B5 et B6.

L'API d'administration (B7) a besoin de fonctions dont les tables ou les envois
appartiennent à d'autres tâches livrées en parallèle. Elles sont isolées ici, avec
un comportement provisoire SÛR, pour que B5 et B6 n'aient qu'à remplacer le corps
de chaque fonction (même signature) :

==============================  =====  ===========================================
Fonction                        Tâche  Comportement provisoire
==============================  =====  ===========================================
``envoyer_invitation``          B6     aucun e-mail (journal applicatif seulement)
``revoquer_sessions``           B5     raccordé (``alpha.comptes.sessions``)
``sessions_actives``            B5     raccordé (``session_appareil``)
``statuts_authenticator``       B5     raccordé (``authenticator_totp``)
``verifier_code_step_up``       B5     raccordé (``alpha.comptes.mfa.verifier_step_up``)
``signalement_en_cours``        B6     ``None``
==============================  =====  ===========================================

Toutes ces fonctions sont appelées sous le contexte tenant de l'établissement,
sauf ``envoyer_invitation``, appelée APRÈS le commit (``transaction.on_commit``),
donc hors de tout contexte : elle reçoit des identifiants, pas d'objet ORM (§ 3.7).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

journal = logging.getLogger("alpha.comptes")

# Statuts d'Authenticator exposés par l'API (UtilisateurListe, § 5.1).
AUTHENTICATOR_ACTIVE = "ACTIVE"
AUTHENTICATOR_NON_CONFIGUREE = "NON_CONFIGUREE"
AUTHENTICATOR_SUSPENDUE = "SUSPENDUE"


def envoyer_invitation(
    etablissement_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
    jeton_clair: str,
    expire_le: datetime.datetime,
) -> None:
    """Envoie l'e-mail d'invitation avec le lien ``/activation?jeton=<jeton_clair>`` (§ 4.3).

    TODO B6 : planifier la tâche Celery d'envoi (gabarit FR « Activez votre compte
    ALPHA »), sous ``tache_tenant``. Appelée par ``transaction.on_commit`` : aucune
    invitation n'est envoyée pour une transaction annulée. Le jeton en clair n'existe
    que dans l'e-mail : ne jamais le journaliser ni le stocker.
    """
    journal.info(
        "Invitation de l'utilisateur %s (établissement %s) : envoi d'e-mail non raccordé (B6).",
        utilisateur_id,
        etablissement_id,
    )


def revoquer_sessions(utilisateur_id: uuid.UUID, *, motif: str = "REVOCATION_ADMIN") -> int:
    """Révoque toutes les sessions ouvertes de l'utilisateur ; renvoie leur nombre (§ 4.8).

    ``session_appareil.revoque_le = now``, ``motif_fin = motif`` et cache Redis invalidé :
    la session Django est refusée (401 ``SESSION_EXPIREE``) et vidée à sa requête suivante.
    """
    from . import sessions
    from .models import Utilisateur

    utilisateur = Utilisateur.objects.filter(pk=utilisateur_id).first()
    if utilisateur is None:
        return 0
    return sessions.revoquer_sessions(utilisateur, motif)


def sessions_actives(utilisateur_id: uuid.UUID) -> list[dict[str, Any]]:
    """Sessions non révoquées et non expirées de l'utilisateur : ``[{id, appareil, ip,
    methode_mfa, cree_le, derniere_activite}]`` (fiche administrateur, § 5.5)."""
    from django.utils import timezone

    from .models import SessionAppareil

    return list(
        SessionAppareil.objects.filter(
            utilisateur_id=utilisateur_id, revoque_le__isnull=True, expire_le__gt=timezone.now()
        )
        .order_by("-derniere_activite")
        .values("id", "appareil", "ip", "methode_mfa", "cree_le", "derniere_activite")
    )


def statuts_authenticator(utilisateur_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Statut de l'Authenticator de chaque utilisateur (``ACTIVE``, ``SUSPENDUE``) ;
    un utilisateur absent du résultat est « NON_CONFIGUREE »."""
    from .models import AuthenticatorTOTP, StatutAuthenticator

    correspondance = {
        StatutAuthenticator.ACTIF: AUTHENTICATOR_ACTIVE,
        StatutAuthenticator.SUSPENDU: AUTHENTICATOR_SUSPENDUE,
    }
    return {
        utilisateur_id: correspondance[statut]
        for utilisateur_id, statut in AuthenticatorTOTP.objects.filter(
            utilisateur_id__in=list(utilisateur_ids), statut__in=list(correspondance)
        ).values_list("utilisateur_id", "statut")
    }


def verifier_code_step_up(utilisateur_id: uuid.UUID, code: str) -> bool:
    """Vérifie le code TOTP de confirmation (« StepUp », § 4.9) de l'utilisateur.

    Même implémentation que ``alpha.core.permissions.StepUpTOTP`` : fenêtre ±1, pas
    CONSOMMÉ (anti-rejeu), limite de 5 essais/min, refus journalisés hors transaction.
    Faux aussi au-delà de la limite de débit. L'appelant RETOURNE sa réponse d'erreur
    (§ 3.3) : ainsi rien de ce qui précède n'est annulé.
    """
    from . import mfa
    from .models import Utilisateur

    utilisateur = Utilisateur.objects.filter(pk=utilisateur_id).first()
    if utilisateur is None or not code:
        return False
    resultat, _ = mfa.verifier_step_up(utilisateur, str(code))
    return resultat == mfa.STEP_UP_OK


def signalement_en_cours(utilisateur_id: uuid.UUID) -> dict[str, Any] | None:
    """Signalement « téléphone perdu » OUVERT : ``{id, statut, signale_le, canal}`` ou ``None``.
    TODO B6 (``signalement_telephone_perdu``)."""
    return None
