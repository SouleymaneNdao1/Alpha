"""Sérialiseurs des routes d'authentification (architecture § 5.1, § 5.2)."""

from __future__ import annotations

from rest_framework import serializers

from alpha.core.schema_erreurs import ErreurSerializer
from alpha.organisation.codes_permission import PERMISSIONS_ADMIN, PERMISSIONS_AUDIT

from .connexion import mot_de_passe_expire, regles_pour
from .models import Utilisateur

# --- Erreurs (documentation OpenAPI) ---------------------------------------------------------


# Format d'erreur : composant « Erreur » commun (alpha.core.schema_erreurs, B7).


class DetailsCodeInvalideSerializer(serializers.Serializer):
    tentatives_restantes = serializers.IntegerField(min_value=0)


class ErreurCodeInvalideSerializer(ErreurSerializer):
    details = DetailsCodeInvalideSerializer()


class DetailsVerrouillageSerializer(serializers.Serializer):
    jusqua = serializers.DateTimeField(
        allow_null=True, help_text="Fin du verrouillage ; null si déblocage administrateur."
    )
    deblocage_administrateur = serializers.BooleanField()


class ErreurVerrouillageSerializer(ErreurSerializer):
    details = DetailsVerrouillageSerializer()


class DetailsTropDeRequetesSerializer(serializers.Serializer):
    reessayer_dans_s = serializers.IntegerField(min_value=0)


class ErreurTropDeRequetesSerializer(ErreurSerializer):
    details = DetailsTropDeRequetesSerializer()


# --- Moi (§ 5.1) --------------------------------------------------------------------------------


class EtablissementMoiSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    raison_sociale = serializers.CharField()
    type = serializers.CharField()
    statut = serializers.CharField()


class RolePrincipalSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    libelle = serializers.CharField()
    unite = serializers.CharField(allow_null=True)


class ReferenceMoiSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    libelle = serializers.CharField()


class AffectationMoiSerializer(serializers.Serializer):
    role = ReferenceMoiSerializer()
    unite = ReferenceMoiSerializer(allow_null=True)
    principal = serializers.BooleanField()


class MoiSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    prenom = serializers.CharField()
    nom = serializers.CharField()
    initiales = serializers.CharField()
    email = serializers.EmailField()
    telephone_mobile = serializers.CharField(allow_null=True)
    langue = serializers.CharField()
    etablissement = EtablissementMoiSerializer(allow_null=True)
    role_principal = RolePrincipalSerializer(allow_null=True)
    affectations = AffectationMoiSerializer(many=True)
    permissions = serializers.ListField(child=serializers.CharField())
    modules = serializers.ListField(child=serializers.CharField())
    signature_bloquee = serializers.BooleanField()
    inactivite_session_min = serializers.IntegerField()
    est_super_admin = serializers.BooleanField()
    mot_de_passe_expire = serializers.BooleanField(
        help_text="Expiration périodique (réglage de l'établissement, P3) atteinte."
    )


def _initiales(utilisateur: Utilisateur) -> str:
    return f"{utilisateur.prenom[:1]}{utilisateur.nom[:1]}".upper()


def donnees_moi(utilisateur: Utilisateur) -> dict:
    """Objet ``Moi`` (lu sous le contexte de l'utilisateur)."""
    regles = regles_pour(utilisateur)
    etablissement = None
    affectations: list[dict] = []
    role_principal = None
    permissions: set[str] = set()
    modules: list[str] = []
    if utilisateur.est_super_admin:
        modules = ["CONSOLE"]
    else:
        from alpha.organisation.models import AffectationRole
        from alpha.tenancy.models import Etablissement

        etab = Etablissement.objects.filter(pk=utilisateur.etablissement_id).first()
        if etab is not None:
            etablissement = {
                "id": etab.id,
                "raison_sociale": etab.raison_sociale,
                "type": etab.type,
                "statut": etab.statut,
            }
        lignes = (
            AffectationRole.objects.actives()
            .filter(utilisateur_id=utilisateur.pk, role__actif=True)
            .select_related("role", "unite")
            .order_by("-principal", "role__ordre", "role__libelle")
        )
        for aff in lignes:
            unite = {"id": aff.unite.id, "libelle": aff.unite.libelle} if aff.unite else None
            affectations.append(
                {
                    "role": {"id": aff.role.id, "libelle": aff.role.libelle},
                    "unite": unite,
                    "principal": aff.principal,
                }
            )
            permissions.update(aff.role.permissions or ())
            if aff.principal and role_principal is None:
                role_principal = {
                    "id": aff.role.id,
                    "libelle": aff.role.libelle,
                    "unite": aff.unite.libelle if aff.unite else None,
                }
        modules = ["COMPTE"]
        if permissions & set(PERMISSIONS_ADMIN):
            modules.append("ADMINISTRATION")
        if permissions & set(PERMISSIONS_AUDIT):
            modules.append("AUDIT")
    return {
        "id": utilisateur.pk,
        "prenom": utilisateur.prenom,
        "nom": utilisateur.nom,
        "initiales": _initiales(utilisateur),
        "email": utilisateur.email,
        "telephone_mobile": utilisateur.telephone_mobile,
        "langue": utilisateur.langue,
        "etablissement": etablissement,
        "role_principal": role_principal,
        "affectations": affectations,
        "permissions": sorted(permissions),
        "modules": modules,
        "signature_bloquee": utilisateur.signature_bloquee,
        "inactivite_session_min": int(regles.inactivite.total_seconds() // 60),
        "est_super_admin": utilisateur.est_super_admin,
        "mot_de_passe_expire": mot_de_passe_expire(utilisateur, regles),
    }


# --- Corps et réponses de /auth --------------------------------------------------------------


class ConnexionSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    mot_de_passe = serializers.CharField(
        max_length=256, trim_whitespace=False, write_only=True, style={"input_type": "password"}
    )


class EtapeConnexionSerializer(serializers.Serializer):
    etape = serializers.ChoiceField(choices=["MFA_REQUIS", "REENROLEMENT_REQUIS"])
    methodes = serializers.ListField(
        child=serializers.ChoiceField(choices=["TOTP", "CODE_SECOURS"]),
        help_text="Méthodes MFA utilisables (TOTP absent si l'Authenticator est suspendu).",
    )


class MfaSerializer(serializers.Serializer):
    code = serializers.CharField(
        required=False, max_length=6, min_length=6, help_text="Code TOTP à 6 chiffres."
    )
    code_secours = serializers.CharField(
        required=False, max_length=20, help_text="Code de secours « XXXX-XXXX »."
    )

    def validate_code(self, valeur: str) -> str:
        if not valeur.isdigit():
            raise serializers.ValidationError("Le code doit comporter 6 chiffres.")
        return valeur

    def validate(self, donnees: dict) -> dict:
        if bool(donnees.get("code")) == bool(donnees.get("code_secours")):
            raise serializers.ValidationError(
                "Renseignez soit le code de l'application, soit un code de secours."
            )
        return donnees


class ConnexionReussieSerializer(serializers.Serializer):
    utilisateur = MoiSerializer()
    codes_secours_restants = serializers.IntegerField(min_value=0)
