"""Sérialiseurs de la console FYXOP (architecture § 5.7, tâche B10).

Les réponses ne contiennent que des métadonnées d'établissement et des compteurs
(``alpha_stats_etablissements``) : aucun contenu (utilisateurs, tâches, journal métier).
"""

from __future__ import annotations

from rest_framework import serializers

from alpha.tenancy.models import StatutEtablissement, TypeEtablissement

from .services import STATUTS_MANUELS


def _code_totp() -> serializers.RegexField:
    return serializers.RegexField(
        r"^[0-9]{6}$",
        write_only=True,
        error_messages={"invalid": "Code à 6 chiffres attendu."},
        help_text="Code TOTP de confirmation (step-up, § 4.9).",
    )


# --- Sorties ----------------------------------------------------------------------------------


class StatsSerializer(serializers.Serializer):
    """Compteurs techniques (aucun contenu)."""

    nb_utilisateurs_actifs = serializers.IntegerField()
    nb_invites = serializers.IntegerField()
    derniere_activite = serializers.DateTimeField(allow_null=True)
    nb_evenements_audit_30j = serializers.IntegerField()
    dernier_controle_statut = serializers.CharField(
        allow_null=True, help_text="INTACTE, ROMPUE ou ERREUR ; null sans contrôle terminé."
    )


class EtablissementConsoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    raison_sociale = serializers.CharField()
    type = serializers.ChoiceField(choices=TypeEtablissement.choices)
    statut = serializers.ChoiceField(choices=StatutEtablissement.choices)
    cree_le = serializers.DateTimeField()
    stats = StatsSerializer()


class EtablissementDetailSerializer(EtablissementConsoleSerializer):
    pays = serializers.CharField()
    fuseau_horaire = serializers.CharField()
    modifie_le = serializers.DateTimeField()
    suspension_manuelle_disponible = serializers.BooleanField(
        help_text="Réglage P6 (ALPHA_PLATEFORME_SUSPENSION_MANUELLE) : le statut est "
        "modifiable depuis la console."
    )


class AdministrateurInviteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    prenom = serializers.CharField()
    nom = serializers.CharField()
    statut = serializers.CharField()


class ProvisionnementReponseSerializer(EtablissementDetailSerializer):
    administrateur = AdministrateurInviteSerializer()


class ReinitialisationReponseSerializer(serializers.Serializer):
    signalement_id = serializers.UUIDField()
    statut = serializers.CharField()
    traite_le = serializers.DateTimeField()


# --- Entrées ----------------------------------------------------------------------------------


class FiltresEtablissementsSerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False, max_length=100, help_text="Recherche : code ou raison sociale."
    )
    statut = serializers.ChoiceField(required=False, choices=StatutEtablissement.choices)


class IdentiteAdministrateurSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    prenom = serializers.CharField(max_length=80)
    nom = serializers.CharField(max_length=80)


class ProvisionnementSerializer(serializers.Serializer):
    code = serializers.RegexField(
        r"^[a-z0-9-]+$",
        max_length=40,
        error_messages={"invalid": "Minuscules, chiffres et tirets uniquement."},
        help_text="Identifiant court et définitif, ex. « banque-atlantique-sn ».",
    )
    raison_sociale = serializers.CharField(max_length=200)
    type = serializers.ChoiceField(choices=TypeEtablissement.choices)
    pays = serializers.RegexField(
        r"^[A-Z]{2}$",
        error_messages={"invalid": "Code pays ISO 3166-1 alpha-2 (ex. SN)."},
    )
    administrateur = IdentiteAdministrateurSerializer()
    # Ailleurs, le code TOTP de confirmation s'appelle « code » (§ 4.9) ; ici « code »
    # désigne déjà l'établissement (§ 5.7) : le code TOTP est donc ``code_totp``.
    code_totp = _code_totp()


class ModificationEtablissementSerializer(serializers.Serializer):
    raison_sociale = serializers.CharField(max_length=200, required=False)
    statut = serializers.ChoiceField(
        required=False,
        choices=StatutEtablissement.choices,
        help_text=f"Seulement si la suspension manuelle est activée (P6) : "
        f"{', '.join(STATUTS_MANUELS)}.",
    )
    motif = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Obligatoire pour un changement de statut (journalisé).",
    )
    code = _code_totp()


class InvitationAdministrateurSerializer(IdentiteAdministrateurSerializer):
    code = _code_totp()


class ReinitialisationAuthenticatorSerializer(serializers.Serializer):
    email = serializers.EmailField(
        max_length=254,
        help_text="Adresse de l'administrateur, telle qu'indiquée sur la demande écrite signée.",
    )
    reference_demande = serializers.CharField(
        max_length=120, help_text="Référence de la demande écrite signée par la direction (P4)."
    )
    commentaire = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Ex. « Appel vidéo avec CNI le 19/10/2026 ».",
    )
    code = _code_totp()
