"""Sérialiseurs de « Mon compte » (``/moi``, § 5.3 ; tâche B9)."""

from __future__ import annotations

from rest_framework import serializers

from .models import Langue, MethodeMfa, StatutSignalement
from .serializers_admin import FORMAT_E164

_MDP = {
    "max_length": 256,
    "trim_whitespace": False,
    "write_only": True,
    "style": {"input_type": "password"},
}
_CODE_TOTP = r"^\d{6}$"


class ProfilSerializer(serializers.Serializer):
    """Corps de ``PATCH /moi`` : l'e-mail n'est pas modifiable (refusé s'il est envoyé)."""

    prenom = serializers.CharField(max_length=80, required=False)
    nom = serializers.CharField(max_length=80, required=False)
    telephone_mobile = serializers.RegexField(
        FORMAT_E164,
        max_length=20,
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages={"invalid": "Format international attendu (ex. +221770000000)."},
    )
    langue = serializers.ChoiceField(choices=Langue.choices, required=False)

    def validate(self, donnees: dict) -> dict:
        if "email" in self.initial_data:
            raise serializers.ValidationError(
                {"email": ["L'adresse e-mail n'est pas modifiable. Contactez un administrateur."]}
            )
        for cle in ("prenom", "nom"):
            if cle in donnees:
                donnees[cle] = donnees[cle].strip()
                if not donnees[cle]:
                    raise serializers.ValidationError({cle: ["Ce champ ne peut pas être vide."]})
        return donnees


class ChangementMotDePasseSerializer(serializers.Serializer):
    actuel = serializers.CharField(**_MDP, help_text="Mot de passe actuel.")
    nouveau = serializers.CharField(**_MDP)
    confirmation = serializers.CharField(**_MDP)
    code = serializers.RegexField(_CODE_TOTP, help_text="Code TOTP de confirmation (step-up).")


class AuthenticatorSecuriteSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(choices=["ACTIVE", "NON_CONFIGUREE", "SUSPENDUE"])
    libelle = serializers.CharField(allow_blank=True)
    active_le = serializers.DateTimeField(allow_null=True)


class SignalementSecuriteSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(choices=StatutSignalement.choices)
    signale_le = serializers.DateTimeField()


class SecuriteSerializer(serializers.Serializer):
    authenticator = AuthenticatorSecuriteSerializer()
    codes_secours_restants = serializers.IntegerField(min_value=0)
    signature_bloquee = serializers.BooleanField()
    signalement = SignalementSecuriteSerializer(
        allow_null=True, help_text="Signalement « téléphone perdu » en cours, sinon null."
    )
    mdp_modifie_le = serializers.DateTimeField(allow_null=True)
    mot_de_passe_expire = serializers.BooleanField(
        help_text="Expiration périodique atteinte (P3) : changement obligatoire."
    )


class ChangementAuthenticatorSerializer(serializers.Serializer):
    code_actuel = serializers.RegexField(
        _CODE_TOTP, help_text="Code de l'application ACTUELLE (step-up)."
    )


class ConfirmationAuthenticatorSerializer(serializers.Serializer):
    code_nouveau = serializers.RegexField(
        _CODE_TOTP, help_text="Premier code de la NOUVELLE application."
    )


class StepUpSerializer(serializers.Serializer):
    code = serializers.RegexField(_CODE_TOTP, help_text="Code TOTP de confirmation (step-up).")


class SessionMoiSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    appareil = serializers.CharField()
    ip = serializers.IPAddressField(allow_null=True)
    methode_mfa = serializers.ChoiceField(choices=MethodeMfa.choices)
    cree_le = serializers.DateTimeField()
    derniere_activite = serializers.DateTimeField()
    courante = serializers.BooleanField(help_text="Session de cet appareil.")


class RevocationMesSessionsSerializer(serializers.Serializer):
    revoquees = serializers.IntegerField(min_value=0)
