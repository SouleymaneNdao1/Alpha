"""Sérialiseurs de l'API du journal d'audit (architecture § 5.1, § 5.6)."""

from __future__ import annotations

from rest_framework import serializers

from alpha.comptes.serializers_admin import EvenementAuditSerializer, presenter_evenement

from .models import ControleIntegriteAudit, StatutControle

__all__ = [
    "ControleSerializer",
    "DernierControleSerializer",
    "EvenementAuditSerializer",
    "IndicateursSerializer",
    "LancementControleSerializer",
    "presenter_evenement",
]


class ControleSerializer(serializers.ModelSerializer):
    """``ControleIntegriteAudit`` (§ 2.2) ; l'empreinte de l'ancre n'est pas exposée."""

    class Meta:
        model = ControleIntegriteAudit
        fields = (
            "id",
            "lance_le",
            "termine_le",
            "declencheur",
            "statut",
            "nb_evenements",
            "dernier_seq",
            "premier_seq_invalide",
            "message",
        )
        read_only_fields = fields


class DernierControleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    statut = serializers.ChoiceField(choices=StatutControle.choices)
    lance_le = serializers.DateTimeField()
    termine_le = serializers.DateTimeField(allow_null=True)
    dernier_seq = serializers.IntegerField(allow_null=True)
    premier_seq_invalide = serializers.IntegerField(
        allow_null=True, help_text="Rang du premier événement invalide si la chaîne est rompue."
    )
    message = serializers.CharField()


class IndicateursSerializer(serializers.Serializer):
    evenements_aujourdhui = serializers.IntegerField()
    connexions_echouees_24h = serializers.IntegerField()
    actions_administration_24h = serializers.IntegerField()
    dernier_controle = DernierControleSerializer(
        allow_null=True,
        help_text="Dernier contrôle terminé (null s'il n'y en a aucun).",
    )
    controle_en_cours = serializers.BooleanField(help_text="Un contrôle est en cours d'exécution.")


class LancementControleSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        help_text="Contrôle créé (statut EN_COURS), à suivre via /audit/controles."
    )
    statut = serializers.ChoiceField(choices=StatutControle.choices)
