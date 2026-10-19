"""Sérialiseurs des parcours par lien e-mail et du téléphone perdu (§ 4.3, § 4.5, § 4.7, § 5.2,
§ 5.5 ; tâche B6)."""

from __future__ import annotations

from rest_framework import serializers

from alpha.core.schema_erreurs import ErreurSerializer

from .models import EtapeJeton, ModeVerification, StatutSignalement

_MDP = {
    "max_length": 256,
    "trim_whitespace": False,
    "write_only": True,
    "style": {"input_type": "password"},
}


# --- Erreurs (documentation) ---------------------------------------------------------------------


class DetailsJetonInvalideSerializer(serializers.Serializer):
    motif = serializers.CharField(
        required=False, help_text="TROP_D_ESSAIS si le lien a été annulé après 5 codes faux."
    )


class ErreurJetonInvalideSerializer(ErreurSerializer):
    details = DetailsJetonInvalideSerializer()


class DetailsAutoTraitementSerializer(serializers.Serializer):
    recours_fyxop = serializers.BooleanField(
        help_text="Vrai si aucun autre administrateur disponible : demande écrite à FYXOP (P4)."
    )


class ErreurAutoTraitementSerializer(ErreurSerializer):
    details = DetailsAutoTraitementSerializer()


# --- Activation et réenrôlement ---------------------------------------------------------------


class InfosActivationSerializer(serializers.Serializer):
    prenom = serializers.CharField()
    etablissement = serializers.CharField(allow_blank=True)
    role = serializers.CharField(allow_blank=True)
    etape = serializers.ChoiceField(choices=EtapeJeton.choices)


class InfosReenrolementSerializer(serializers.Serializer):
    prenom = serializers.CharField()
    etablissement = serializers.CharField(allow_blank=True)
    etape = serializers.ChoiceField(choices=EtapeJeton.choices)


class DefinitionMotDePasseSerializer(serializers.Serializer):
    mot_de_passe = serializers.CharField(**_MDP)
    confirmation = serializers.CharField(**_MDP)


class MotDePasseActuelSerializer(serializers.Serializer):
    mot_de_passe = serializers.CharField(**_MDP, help_text="Mot de passe ACTUEL du compte.")


class EnrolementAuthenticatorSerializer(serializers.Serializer):
    qr_svg = serializers.CharField(help_text="QR code SVG de l'URI otpauth:// (affichage seul).")
    secret_affichable = serializers.CharField(
        help_text="Secret base32 par groupes de 4, pour une saisie manuelle."
    )
    emetteur = serializers.CharField()
    compte = serializers.CharField()


class CodeTotpSerializer(serializers.Serializer):
    code = serializers.RegexField(r"^\d{6}$", help_text="Code à 6 chiffres de l'application.")


class CodesSecoursSerializer(serializers.Serializer):
    codes_secours = serializers.ListField(
        child=serializers.CharField(), help_text="10 codes « XXXX-XXXX », affichés une seule fois."
    )


class TerminerSerializer(serializers.Serializer):
    codes_conserves = serializers.BooleanField()

    def validate_codes_conserves(self, valeur: bool) -> bool:
        if not valeur:
            raise serializers.ValidationError("Confirmez avoir conservé vos codes de secours.")
        return valeur


# --- Mot de passe oublié -----------------------------------------------------------------------


class OubliSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class AccepteSerializer(serializers.Serializer):
    message = serializers.CharField()


class InfosReinitialisationSerializer(serializers.Serializer):
    email_masque = serializers.CharField()
    methodes = serializers.ListField(
        child=serializers.ChoiceField(choices=["TOTP", "CODE_SECOURS"]),
        help_text="Preuves MFA utilisables ; vide : passer par « Téléphone perdu ».",
    )


class ReinitialisationSerializer(serializers.Serializer):
    mot_de_passe = serializers.CharField(**_MDP)
    confirmation = serializers.CharField(**_MDP)
    code = serializers.RegexField(r"^\d{6}$", required=False, help_text="Code TOTP.")
    code_secours = serializers.CharField(
        required=False, max_length=20, help_text="Code de secours « XXXX-XXXX »."
    )

    def validate(self, donnees: dict) -> dict:
        if bool(donnees.get("code")) == bool(donnees.get("code_secours")):
            raise serializers.ValidationError(
                "Renseignez soit le code de l'application, soit un code de secours."
            )
        return donnees


# --- Téléphone perdu -------------------------------------------------------------------------


class TelephonePerduSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    mot_de_passe = serializers.CharField(**_MDP)


class ReferencePersonneSignalementSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()


class UtilisateurSignalementSerializer(ReferencePersonneSignalementSerializer):
    email = serializers.EmailField()


class SignalementTelephoneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    utilisateur = UtilisateurSignalementSerializer()
    canal = serializers.CharField()
    statut = serializers.ChoiceField(choices=StatutSignalement.choices)
    signale_le = serializers.DateTimeField()
    traite_par = ReferencePersonneSignalementSerializer(allow_null=True)
    mode_verification = serializers.CharField(allow_null=True)
    reference_demande = serializers.CharField(allow_null=True)
    commentaire = serializers.CharField(allow_blank=True)
    traite_le = serializers.DateTimeField(allow_null=True)


class PageSignalementsSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SignalementTelephoneSerializer(many=True)


class ReinitialisationSignalementSerializer(serializers.Serializer):
    mode_verification = serializers.ChoiceField(choices=ModeVerification.choices)
    commentaire = serializers.CharField(max_length=2000, allow_blank=True, default="")
    code = serializers.RegexField(
        r"^\d{6}$", help_text="Code TOTP de l'administrateur (confirmation)."
    )


class AnnulationSignalementSerializer(serializers.Serializer):
    commentaire = serializers.CharField(max_length=2000, allow_blank=True, default="")
    code = serializers.RegexField(
        r"^\d{6}$", help_text="Code TOTP de l'administrateur (confirmation)."
    )
