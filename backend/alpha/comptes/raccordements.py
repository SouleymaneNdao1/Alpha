"""Points de raccordement de l'administration (B7) vers les tâches B5 et B6.

L'API d'administration (B7) a besoin de fonctions dont les tables ou les envois
appartiennent à d'autres tâches livrées en parallèle. Elles sont isolées ici, avec
un comportement provisoire SÛR, pour que B5 et B6 n'aient qu'à remplacer le corps
de chaque fonction (même signature) :

==============================  =====  ===========================================
Fonction                        Tâche  Comportement provisoire
==============================  =====  ===========================================
``envoyer_invitation``          B6     aucun e-mail (journal applicatif seulement)
``revoquer_sessions``           B5     0 session révoquée (pas encore de table)
``sessions_actives``            B5     liste vide
``statuts_authenticator``       B5     « NON_CONFIGUREE » pour tous
``verifier_code_step_up``       B5     REFUS (échec fermé) : aucun code accepté
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

    TODO B5 : ``session_appareil.revoque_le = now``, ``motif_fin = motif``, suppression
    des sessions Django correspondantes et invalidation du cache Redis.
    En attendant : un utilisateur SUSPENDU est de toute façon rejeté à la requête
    suivante (``Utilisateur.is_active`` est faux, ``ModelBackend.get_user`` renvoie
    un anonyme).
    """
    return 0


def sessions_actives(utilisateur_id: uuid.UUID) -> list[dict[str, Any]]:
    """Sessions non révoquées de l'utilisateur : ``[{id, appareil, ip, methode_mfa, cree_le,
    derniere_activite}]`` (fiche administrateur, § 5.5). TODO B5 (``session_appareil``)."""
    return []


def statuts_authenticator(utilisateur_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Statut de l'Authenticator de chaque utilisateur (``ACTIVE``, ``SUSPENDUE``) ;
    un utilisateur absent du résultat est « NON_CONFIGUREE ». TODO B5 (``authenticator_totp``)."""
    return {}


def verifier_code_step_up(utilisateur_id: uuid.UUID, code: str) -> bool:
    """Vérifie le code TOTP de confirmation (« StepUp », § 4.9) de l'utilisateur.

    TODO B5 : brancher ``alpha.core.permissions.StepUpTOTP`` (fenêtre ±1, anti-rejeu).
    ÉCHEC FERMÉ tant que B5 n'est pas livré : aucun code n'est accepté, donc
    ``PATCH /admin/parametres-securite`` répond 401 ``CODE_INVALIDE``.
    """
    return False


def signalement_en_cours(utilisateur_id: uuid.UUID) -> dict[str, Any] | None:
    """Signalement « téléphone perdu » OUVERT : ``{id, statut, signale_le, canal}`` ou ``None``.
    TODO B6 (``signalement_telephone_perdu``)."""
    return None
