"""Notifications : préférences d'envoi et notifications in-app (§ 2.2, tâche B9).

- ``PreferencesNotification`` : une ligne par utilisateur (1–1), créée à l'invitation
  (``alpha.notifications.services.creer_preferences_defaut``) ou, à défaut, à la
  première lecture. Les canaux SMS et « Téléphone » (notification mobile) sont
  seulement ENREGISTRÉS : leur envoi arrive au sprint 4 (P9). Les alertes de
  sécurité partent toujours par e-mail, quel que soit le réglage.
- ``Notification`` : cloche du bandeau (in-app), alimentée par les signaux des
  tâches et des délégations (``alpha.notifications.recepteurs``).

Tables (*) du § 3.5 : politique « tenant ou plateforme » (``etablissement`` NULL
pour un super-administrateur FYXOP), ``utilisateur_id`` du même établissement.
"""

from __future__ import annotations

import datetime
import uuid

from django.conf import settings
from django.db import models

from alpha.tenancy.models import TenantOuPlateformeModel

HEURE_RESUME_DEFAUT = datetime.time(7, 30)


class PreferencesNotification(TenantOuPlateformeModel):
    """Canaux de notification choisis par l'utilisateur (onglet « Notifications »)."""

    AUDIT_CHAMPS = ("email", "push", "sms", "resume_quotidien", "heure_resume")

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="preferences_notification",
    )
    email = models.BooleanField("e-mail", default=True)
    push = models.BooleanField(
        "notification mobile", default=False, help_text="Enregistré ; envoi au sprint 4."
    )
    sms = models.BooleanField("SMS", default=False, help_text="Enregistré ; envoi au sprint 4.")
    resume_quotidien = models.BooleanField("résumé quotidien", default=False)
    heure_resume = models.TimeField("heure du résumé", default=HEURE_RESUME_DEFAUT)
    par_evenement = models.JSONField(
        "surcharges par type d'événement", default=dict, blank=True, help_text="Réservé."
    )
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        db_table = "preferences_notification"
        verbose_name = "préférences de notification"
        verbose_name_plural = "préférences de notification"

    def __str__(self) -> str:
        return f"Préférences de {self.utilisateur_id}"


class TypeNotification(models.TextChoices):
    """Types connus au sprint 1 (la colonne reste ouverte aux modules suivants)."""

    TACHE_NOUVELLE = "TACHE_NOUVELLE", "Nouvelle tâche"
    ABSENCE_VALIDEE = "ABSENCE_VALIDEE", "Absence validée"
    ABSENCE_REFUSEE = "ABSENCE_REFUSEE", "Absence refusée"
    DELEGATION_PROPOSEE = "DELEGATION_PROPOSEE", "Délégation proposée"
    DELEGATION_RECUE = "DELEGATION_RECUE", "Délégation reçue"
    DELEGATION_ANNULEE = "DELEGATION_ANNULEE", "Délégation annulée"
    DELEGATION_ACTIVE = "DELEGATION_ACTIVE", "Délégation en vigueur"
    DELEGATION_TERMINEE = "DELEGATION_TERMINEE", "Délégation terminée"


class Notification(TenantOuPlateformeModel):
    """Notification in-app d'un utilisateur (cloche du bandeau)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="destinataire",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField("type", max_length=40)
    titre = models.CharField("titre", max_length=200)
    corps = models.TextField("corps", blank=True, default="")
    lien = models.CharField("lien (route du frontend)", max_length=300, blank=True, default="")
    lue_le = models.DateTimeField("lue le", null=True, blank=True)
    cree_le = models.DateTimeField("créée le", auto_now_add=True)

    class Meta:
        db_table = "notification"
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        indexes = [
            models.Index(
                "utilisateur",
                "lue_le",
                models.F("cree_le").desc(),
                name="notification_util_lue_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} · {self.titre}"
