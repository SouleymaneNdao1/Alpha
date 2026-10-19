"""Sérialiseurs de ``/moi/preferences-notification`` et ``/moi/notifications`` (§ 5.3, B9)."""

from __future__ import annotations

from rest_framework import serializers

from .models import Notification


class PreferencesNotificationSerializer(serializers.Serializer):
    """Corps du PUT (tous les champs) et réponse du GET."""

    email = serializers.BooleanField(
        help_text="Notifications par e-mail. Les alertes de sécurité partent toujours par e-mail."
    )
    push = serializers.BooleanField(
        help_text="Notification mobile (« Téléphone ») : enregistrée, envoi au sprint 4."
    )
    sms = serializers.BooleanField(help_text="SMS : enregistré, envoi au sprint 4.")
    resume_quotidien = serializers.BooleanField()
    heure_resume = serializers.TimeField(
        format="%H:%M", input_formats=["%H:%M", "%H:%M:%S"], help_text="« HH:MM »."
    )


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "titre", "corps", "lien", "lue_le", "cree_le"]
        read_only_fields = fields


class PageNotificationsSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = NotificationSerializer(many=True)
    non_lues = serializers.IntegerField(help_text="Nombre total de notifications non lues.")
