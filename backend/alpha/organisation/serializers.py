"""Sérialiseurs de l'administration de l'organisation : rôles, permissions, unités.

Voir § 5.1 (objet ``Role``) et § 5.5 (routes ``/admin``).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Count
from rest_framework import serializers

from alpha.comptes.models import StatutUtilisateur

from .codes_permission import CodePermission
from .models import AffectationRole, Role, TypeUnite, UniteOrganisationnelle

FORMAT_CODE_ROLE = r"^[a-z0-9]+(-[a-z0-9]+)*$"

#: Libellés courts des permissions (matrice des habilitations) ; description = libellé long.
LIBELLES_PERMISSIONS = {
    CodePermission.ADMIN_UTILISATEURS: "Utilisateurs",
    CodePermission.ADMIN_ROLES: "Rôles et habilitations",
    CodePermission.ADMIN_ORGANISATION: "Organisation",
    CodePermission.ADMIN_SECURITE: "Sécurité",
    CodePermission.ADMIN_ABSENCES: "Absences",
    CodePermission.AUDIT_LECTURE: "Journal d'audit (lecture)",
    CodePermission.AUDIT_EXPORT: "Journal d'audit (export)",
}


# --- Rôles --------------------------------------------------------------------------------------


def titulaires_par_role() -> dict[uuid.UUID, int]:
    """Nombre d'utilisateurs ACTIFS ayant une affectation en cours, par rôle."""
    return {
        ligne["role_id"]: ligne["n"]
        for ligne in AffectationRole.objects.en_cours()
        .filter(utilisateur__statut=StatutUtilisateur.ACTIF)
        .values("role_id")
        .annotate(n=Count("utilisateur_id", distinct=True))
    }


def presenter_role(role: Role, titulaires: dict[uuid.UUID, int] | None = None) -> dict[str, Any]:
    """``Role`` (§ 5.1) ; ``vacant`` : aucun titulaire actif."""
    if titulaires is None:
        titulaires = titulaires_par_role()
    nb = titulaires.get(role.id, 0)
    return {
        "id": role.id,
        "code": role.code,
        "libelle": role.libelle,
        "description": role.description,
        "permissions": sorted(role.permissions),
        "est_systeme": role.est_systeme,
        "actif": role.actif,
        "ordre": role.ordre,
        "nb_titulaires": nb,
        "vacant": nb == 0,
    }


class RoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    libelle = serializers.CharField()
    description = serializers.CharField()
    permissions = serializers.ListField(child=serializers.ChoiceField(CodePermission.choices))
    est_systeme = serializers.BooleanField()
    actif = serializers.BooleanField()
    ordre = serializers.IntegerField()
    nb_titulaires = serializers.IntegerField()
    vacant = serializers.BooleanField()


class _ChampsRole(serializers.Serializer):
    libelle = serializers.CharField(max_length=100)
    description = serializers.CharField(allow_blank=True, required=False)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(
            CodePermission.choices,
            error_messages={"invalid_choice": "Code de permission inconnu : « {input} »."},
        ),
        required=False,
    )
    ordre = serializers.IntegerField(min_value=0, max_value=32767, required=False)

    def validate_libelle(self, valeur: str) -> str:
        valeur = valeur.strip()
        if not valeur:
            raise serializers.ValidationError("Le libellé est obligatoire.")
        return valeur


class CreationRoleSerializer(_ChampsRole):
    """Corps de ``POST /admin/roles``."""

    code = serializers.RegexField(
        FORMAT_CODE_ROLE,
        max_length=50,
        required=False,
        error_messages={"invalid": "Minuscules, chiffres et tirets (ex. « analyste-credit »)."},
    )


class ModificationRoleSerializer(_ChampsRole):
    """Corps de ``PATCH /admin/roles/{id}`` (le code n'est pas modifiable)."""


class PermissionSerializer(serializers.Serializer):
    code = serializers.CharField()
    libelle = serializers.CharField()
    description = serializers.CharField()


def presenter_permissions() -> list[dict[str, str]]:
    return [
        {"code": code, "libelle": LIBELLES_PERMISSIONS.get(code, code), "description": libelle}
        for code, libelle in CodePermission.choices
    ]


# --- Unités ---------------------------------------------------------------------------------------


def presenter_unite(unite: UniteOrganisationnelle) -> dict[str, Any]:
    return {
        "id": unite.id,
        "parent_id": unite.parent_id,
        "type": unite.type,
        "code": unite.code,
        "libelle": unite.libelle,
        "actif": unite.actif,
    }


def arbre_des_unites() -> list[dict[str, Any]]:
    """Arbre complet des unités de l'établissement (racines triées, enfants imbriqués)."""
    noeuds: dict[uuid.UUID, dict[str, Any]] = {}
    unites = list(UniteOrganisationnelle.objects.order_by("libelle", "code"))
    for unite in unites:
        noeuds[unite.id] = {**presenter_unite(unite), "enfants": []}
    racines = []
    for unite in unites:
        noeud = noeuds[unite.id]
        parent = noeuds.get(unite.parent_id) if unite.parent_id else None
        (parent["enfants"] if parent else racines).append(noeud)
    return racines


class UniteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    parent_id = serializers.UUIDField(allow_null=True)
    type = serializers.ChoiceField(TypeUnite.choices)
    code = serializers.CharField()
    libelle = serializers.CharField()
    actif = serializers.BooleanField()


class UniteArbreSerializer(UniteSerializer):
    """Nœud de l'arbre des unités (``enfants`` récursif)."""


UniteArbreSerializer._declared_fields["enfants"] = UniteArbreSerializer(many=True)


def _parent(valeur: uuid.UUID | None) -> UniteOrganisationnelle | None:
    if valeur is None:
        return None
    parent = UniteOrganisationnelle.objects.filter(id=valeur).first()
    if parent is None:
        raise serializers.ValidationError("Unité parente inconnue.")
    return parent


class _ChampsUnite(serializers.Serializer):
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    type = serializers.ChoiceField(TypeUnite.choices)
    code = serializers.CharField(max_length=40)
    libelle = serializers.CharField(max_length=150)
    actif = serializers.BooleanField(required=False)

    def validate_parent_id(self, valeur):
        return _parent(valeur)

    def validate_code(self, valeur: str) -> str:
        valeur = valeur.strip()
        if not valeur:
            raise serializers.ValidationError("Le code est obligatoire.")
        return valeur

    def validate_libelle(self, valeur: str) -> str:
        valeur = valeur.strip()
        if not valeur:
            raise serializers.ValidationError("Le libellé est obligatoire.")
        return valeur

    def champs_modele(self) -> dict[str, Any]:
        donnees = dict(self.validated_data)
        if "parent_id" in donnees:
            donnees["parent"] = donnees.pop("parent_id")
        return donnees


class CreationUniteSerializer(_ChampsUnite):
    """Corps de ``POST /admin/unites``."""


class ModificationUniteSerializer(_ChampsUnite):
    """Corps de ``PATCH /admin/unites/{id}`` (tous les champs facultatifs)."""
