"""Représentation API des absences et délégations (§ 5.3, § 5.4)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import MotifAbsence, StatutAbsence, StatutDelegation


class PersonneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()


class RoleCourtSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    libelle = serializers.CharField()


def _personne(utilisateur) -> dict | None:
    if utilisateur is None:
        return None
    return {"id": utilisateur.pk, "nom": utilisateur.nom_complet}


def _role(role) -> dict | None:
    return None if role is None else {"id": role.pk, "libelle": role.libelle}


class DelegationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    delegataire = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    statut = serializers.ChoiceField(choices=StatutDelegation.choices)

    @extend_schema_field(PersonneSerializer)
    def get_delegataire(self, delegation) -> dict | None:
        return _personne(delegation.delegataire)

    @extend_schema_field(RoleCourtSerializer(allow_null=True))
    def get_role(self, delegation) -> dict | None:
        return _role(delegation.role)


class AbsenceSerializer(serializers.Serializer):
    """Absence + sa délégation. Contexte : ``delegations`` ({absence_id: Delegation})."""

    id = serializers.UUIDField()
    demandeur = serializers.SerializerMethodField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    motif = serializers.ChoiceField(choices=MotifAbsence.choices)
    motif_libelle = serializers.SerializerMethodField()
    commentaire = serializers.CharField()
    statut = serializers.ChoiceField(choices=StatutAbsence.choices)
    valideur = serializers.SerializerMethodField()
    decide_le = serializers.DateTimeField(allow_null=True)
    motif_refus = serializers.CharField()
    cree_le = serializers.DateTimeField()
    delegation = serializers.SerializerMethodField()

    @extend_schema_field(PersonneSerializer)
    def get_demandeur(self, absence) -> dict | None:
        return _personne(absence.utilisateur)

    def get_motif_libelle(self, absence) -> str:
        return MotifAbsence(absence.motif).label

    @extend_schema_field(PersonneSerializer(allow_null=True))
    def get_valideur(self, absence) -> dict | None:
        return _personne(absence.valideur)

    @extend_schema_field(DelegationSerializer(allow_null=True))
    def get_delegation(self, absence) -> dict | None:
        delegation = self.context.get("delegations", {}).get(absence.pk)
        return None if delegation is None else DelegationSerializer(delegation).data


class AbsenceDetailSerializer(AbsenceSerializer):
    """``GET /absences/{id}`` : ce que l'utilisateur courant peut faire."""

    peut_decider = serializers.SerializerMethodField()

    def get_peut_decider(self, absence) -> bool:
        return bool(self.context.get("peut_decider"))


class CreationAbsenceSerializer(serializers.Serializer):
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    motif = serializers.ChoiceField(choices=MotifAbsence.choices)
    commentaire = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000
    )
    delegataire_id = serializers.UUIDField()
    role_id = serializers.UUIDField(
        required=False, allow_null=True, default=None, help_text="Vide : tous vos rôles."
    )


class RefusSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=2000)


class DelegatairePossibleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    role_principal = serializers.CharField(allow_null=True)
    pouvoirs_suffisants = serializers.BooleanField(
        help_text="Pouvoirs au moins égaux aux vôtres (P5) ; sinon la demande sera refusée."
    )


class DelegationRecueSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    delegant = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    statut = serializers.ChoiceField(choices=StatutDelegation.choices)
    effective = serializers.SerializerMethodField()

    @extend_schema_field(PersonneSerializer)
    def get_delegant(self, delegation) -> dict | None:
        return _personne(delegation.delegant)

    @extend_schema_field(RoleCourtSerializer(allow_null=True))
    def get_role(self, delegation) -> dict | None:
        return _role(delegation.role)

    def get_effective(self, delegation) -> bool:
        maintenant = self.context["maintenant"]
        return (
            delegation.statut == StatutDelegation.ACTIVE
            and delegation.debut <= maintenant < delegation.fin
        )


# --- Administration de l'établissement (§ 5.5, B13) ----------------------------------------------


class FiltresAdminSerializer(serializers.Serializer):
    """Paramètres communs de ``/admin/absences`` et ``/admin/delegations``."""

    du = serializers.DateField(required=False, help_text="Période chevauchant ce jour ou après.")
    au = serializers.DateField(required=False, help_text="Période chevauchant ce jour ou avant.")
    utilisateur_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if attrs.get("du") and attrs.get("au") and attrs["au"] < attrs["du"]:
            raise serializers.ValidationError({"au": ["« au » doit suivre « du »."]})
        return attrs


class FiltresAbsencesAdminSerializer(FiltresAdminSerializer):
    statut = serializers.ChoiceField(choices=StatutAbsence.choices, required=False)


class FiltresDelegationsAdminSerializer(FiltresAdminSerializer):
    statut = serializers.ChoiceField(choices=StatutDelegation.choices, required=False)


class AbsenceAdminSerializer(AbsenceSerializer):
    """Ligne de ``GET /admin/absences``. Contexte : ``delegations``, ``moi`` (id)."""

    peut_decider = serializers.SerializerMethodField()

    def get_peut_decider(self, absence) -> bool:
        # La vue exige admin.absences : seul l'absent lui-même ne peut pas décider.
        moi = self.context.get("moi")
        return absence.statut == StatutAbsence.SOUMISE and absence.utilisateur_id != moi


class DelegationAdminSerializer(serializers.Serializer):
    """Ligne de ``GET /admin/delegations``. Contexte : ``maintenant``."""

    id = serializers.UUIDField()
    origine = serializers.CharField()
    absence_id = serializers.UUIDField(allow_null=True)
    delegant = serializers.SerializerMethodField()
    delegataire = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    statut = serializers.ChoiceField(choices=StatutDelegation.choices)
    effective = serializers.SerializerMethodField()
    activee_le = serializers.DateTimeField(allow_null=True)
    terminee_le = serializers.DateTimeField(allow_null=True)
    cree_le = serializers.DateTimeField()

    @extend_schema_field(PersonneSerializer)
    def get_delegant(self, delegation) -> dict | None:
        return _personne(delegation.delegant)

    @extend_schema_field(PersonneSerializer)
    def get_delegataire(self, delegation) -> dict | None:
        return _personne(delegation.delegataire)

    @extend_schema_field(RoleCourtSerializer(allow_null=True))
    def get_role(self, delegation) -> dict | None:
        return _role(delegation.role)

    def get_effective(self, delegation) -> bool:
        maintenant = self.context["maintenant"]
        return (
            delegation.statut == StatutDelegation.ACTIVE
            and delegation.debut <= maintenant < delegation.fin
        )


class CreationAbsenceAdminSerializer(CreationAbsenceSerializer):
    utilisateur_id = serializers.UUIDField(help_text="Utilisateur absent (actif).")
    role_id = serializers.UUIDField(
        required=False, allow_null=True, default=None, help_text="Vide : tous ses rôles."
    )
    valider = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Valider aussitôt (même contrôle P5 qu'une validation séparée).",
    )


class RevocationSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=2000)


class CandidatSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    role_principal = serializers.CharField(allow_null=True)
    pouvoirs_suffisants = serializers.BooleanField(
        allow_null=True,
        help_text="Pouvoirs au moins égaux à ceux de « pour » (P5) ; null sans « pour ».",
    )
