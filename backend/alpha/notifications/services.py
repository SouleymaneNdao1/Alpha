"""Services des notifications (tâche B9).

À appeler sous le contexte tenant de l'utilisateur concerné.

- ``creer_preferences_defaut(utilisateur)`` : préférences par défaut (§ 2.2), à
  l'invitation (B7) ; idempotent ;
- ``preferences_de(utilisateur)`` : préférences, créées par défaut si absentes
  (comptes créés avant B9 ou hors invitation) ;
- ``modifier_preferences(utilisateur, **valeurs)`` : enregistrement + audit ;
- ``notifier(destinataires, type, titre, corps, lien)`` : notifications in-app,
  écrites DANS la transaction de l'action qui les déclenche ;
- ``marquer_lue`` / ``tout_lire`` / ``non_lues``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser

from .models import Notification, PreferencesNotification

CHAMPS_PREFERENCES = ("email", "push", "sms", "resume_quotidien", "heure_resume")


def _pk(valeur: Any) -> Any:
    return getattr(valeur, "pk", valeur)


# --- Préférences ------------------------------------------------------------------------------


def creer_preferences_defaut(utilisateur) -> PreferencesNotification:
    """Préférences par défaut (e-mail oui ; SMS, mobile, résumé non ; 07:30). Idempotent."""
    existantes = PreferencesNotification.objects.filter(utilisateur_id=utilisateur.pk).first()
    if existantes is not None:
        return existantes
    try:
        with transaction.atomic():
            return PreferencesNotification.objects.create(
                utilisateur=utilisateur, etablissement_id=utilisateur.etablissement_id
            )
    except IntegrityError:  # création concurrente
        return PreferencesNotification.objects.get(utilisateur_id=utilisateur.pk)


def preferences_de(utilisateur) -> PreferencesNotification:
    return creer_preferences_defaut(utilisateur)


def modifier_preferences(utilisateur, **valeurs: Any) -> PreferencesNotification:
    """Enregistre les préférences (SMS et mobile : enregistrés seulement, envoi au S4)."""
    preferences = (
        PreferencesNotification.objects.select_for_update()
        .filter(utilisateur_id=utilisateur.pk)
        .first()
    ) or creer_preferences_defaut(utilisateur)
    modifies = [
        c for c in CHAMPS_PREFERENCES if c in valeurs and getattr(preferences, c) != valeurs[c]
    ]
    if not modifies:
        return preferences
    avant = extraire_champs(preferences, modifies)
    for champ in modifies:
        setattr(preferences, champ, valeurs[champ])
    preferences.save()
    journaliser(
        "notifications.preferences.modifiees",
        Categorie.MODIFICATION,
        objet=("comptes.utilisateur", utilisateur.pk),
        objet_libelle=utilisateur.nom_complet,
        avant=avant,
        apres=extraire_champs(preferences, modifies),
        detail="Préférences de notification modifiées",
        acteur=utilisateur,
    )
    return preferences


# --- Notifications in-app ---------------------------------------------------------------------


def notifier(
    destinataires: Iterable[Any],
    *,
    type: str,
    titre: str,
    corps: str = "",
    lien: str = "",
) -> list[Notification]:
    """Une notification par destinataire distinct (instances ou identifiants)."""
    vus: set[uuid.UUID] = set()
    lignes = []
    for destinataire in destinataires:
        if destinataire is None:
            continue
        pk = _pk(destinataire)
        if pk in vus:
            continue
        vus.add(pk)
        lignes.append(
            Notification(
                utilisateur_id=pk, type=type[:40], titre=titre[:200], corps=corps, lien=lien[:300]
            )
        )
    for ligne in lignes:
        ligne.save()
    return lignes


def non_lues(utilisateur) -> int:
    return Notification.objects.filter(utilisateur_id=utilisateur.pk, lue_le__isnull=True).count()


def marquer_lue(utilisateur, notification_id: uuid.UUID) -> bool:
    """Faux si la notification n'existe pas ou n'appartient pas à l'utilisateur."""
    notification = Notification.objects.filter(
        pk=notification_id, utilisateur_id=utilisateur.pk
    ).first()
    if notification is None:
        return False
    if notification.lue_le is None:
        notification.lue_le = timezone.now()
        notification.save(update_fields=["lue_le"])
    return True


def tout_lire(utilisateur) -> int:
    return Notification.objects.filter(utilisateur_id=utilisateur.pk, lue_le__isnull=True).update(
        lue_le=timezone.now()
    )
