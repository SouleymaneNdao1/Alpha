"""API d'administration de l'organisation : ``/api/v1/admin/roles``, ``/permissions``, ``/unites``
(§ 5.5, tâche B7).

Permissions (§ 5.5) :
- catalogue des rôles : lecture ``admin.roles`` ou ``admin.utilisateurs`` (choix du rôle à
  l'invitation) ; écriture ``admin.roles`` ;
- liste des permissions (matrice des habilitations) : ``admin.roles`` ;
- unités : lecture ``admin.organisation`` ou ``admin.utilisateurs`` ;
  écriture ``admin.organisation``.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.core.erreurs import VALIDATION, reponse_erreur
from alpha.core.schema_erreurs import erreurs

from . import services
from .codes_permission import CodePermission as C
from .models import Role, UniteOrganisationnelle
from .permissions import Perm
from .serializers import (
    CreationRoleSerializer,
    CreationUniteSerializer,
    ModificationRoleSerializer,
    ModificationUniteSerializer,
    PermissionSerializer,
    RoleSerializer,
    UniteArbreSerializer,
    UniteSerializer,
    arbre_des_unites,
    presenter_permissions,
    presenter_role,
    presenter_unite,
    titulaires_par_role,
)

TAG_ROLES = "Administration · rôles et habilitations"
TAG_UNITES = "Administration · organisation"

LectureRoles = Perm(C.ADMIN_ROLES, C.ADMIN_UTILISATEURS)
EcritureRoles = Perm(C.ADMIN_ROLES)
LectureUnites = Perm(C.ADMIN_ORGANISATION, C.ADMIN_UTILISATEURS)
EcritureUnites = Perm(C.ADMIN_ORGANISATION)


def _role_ou_404(role_id) -> Role:
    role = Role.objects.filter(id=role_id).first()
    if role is None:
        raise NotFound()
    return role


def _unite_ou_404(unite_id) -> UniteOrganisationnelle:
    unite = UniteOrganisationnelle.objects.filter(id=unite_id).first()
    if unite is None:
        raise NotFound()
    return unite


# --- Rôles --------------------------------------------------------------------------------------


class RolesVue(APIView):
    def get_permissions(self):
        return [LectureRoles()] if self.request.method == "GET" else [EcritureRoles()]

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_roles_liste",
        summary="Catalogue des rôles",
        parameters=[
            OpenApiParameter(
                "actif", OpenApiTypes.BOOL, description="true : actifs ; false : inactifs."
            )
        ],
        responses={200: RoleSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        qs = Role.objects.order_by("ordre", "libelle")
        actif = request.query_params.get("actif")
        if actif is not None:
            if actif.lower() not in ("true", "false", "1", "0"):
                return reponse_erreur(VALIDATION, details={"actif": ["true ou false attendu."]})
            qs = qs.filter(actif=actif.lower() in ("true", "1"))
        titulaires = titulaires_par_role()
        return Response([presenter_role(r, titulaires) for r in qs])

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_roles_creer",
        summary="Ajouter un rôle au catalogue",
        description="`code` facultatif : dérivé du libellé (« Analyste crédit » → "
        "« analyste-credit »).",
        request=CreationRoleSerializer,
        responses={
            201: RoleSerializer,
            **erreurs(400, 409, r409="LIBELLE_EXISTE ou CODE_EXISTE."),
        },
    )
    def post(self, request):
        entree = CreationRoleSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        role = services.creer_role(par=request.user, **entree.validated_data)
        return Response(presenter_role(role), status=status.HTTP_201_CREATED)


class RoleVue(APIView):
    permission_classes = [EcritureRoles]

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_role_modifier",
        summary="Modifier un rôle (libellé, description, habilitations, ordre)",
        request=ModificationRoleSerializer,
        responses={
            200: RoleSerializer,
            **erreurs(
                400,
                404,
                409,
                r409="ROLE_SYSTEME (permissions d'un rôle système), LIBELLE_EXISTE ou "
                "DERNIER_ADMINISTRATEUR.",
            ),
        },
    )
    def patch(self, request, role_id):
        role = _role_ou_404(role_id)
        entree = ModificationRoleSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        services.modifier_role(role, par=request.user, **entree.validated_data)
        return Response(presenter_role(role))


class _ActivationRoleVue(APIView):
    permission_classes = [EcritureRoles]
    actif: bool

    def _changer(self, request, role_id):
        role = _role_ou_404(role_id)
        services.changer_activation_role(role, par=request.user, actif=self.actif)
        return Response(presenter_role(role))


_REPONSES_ACTIVATION = {
    200: RoleSerializer,
    **erreurs(404, 409, r409="ROLE_SYSTEME ou DERNIER_ADMINISTRATEUR."),
}


class DesactiverRoleVue(_ActivationRoleVue):
    actif = False

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_role_desactiver",
        summary="Désactiver un rôle",
        request=None,
        responses=_REPONSES_ACTIVATION,
    )
    def post(self, request, role_id):
        return self._changer(request, role_id)


class ActiverRoleVue(_ActivationRoleVue):
    actif = True

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_role_activer",
        summary="Réactiver un rôle",
        request=None,
        responses=_REPONSES_ACTIVATION,
    )
    def post(self, request, role_id):
        return self._changer(request, role_id)


class PermissionsVue(APIView):
    permission_classes = [EcritureRoles]

    @extend_schema(
        tags=[TAG_ROLES],
        operation_id="admin_permissions_liste",
        summary="Codes de permission système (matrice des habilitations)",
        responses={200: PermissionSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        return Response(presenter_permissions())


# --- Unités ------------------------------------------------------------------------------------


class UnitesVue(APIView):
    def get_permissions(self):
        return [LectureUnites()] if self.request.method == "GET" else [EcritureUnites()]

    @extend_schema(
        tags=[TAG_UNITES],
        operation_id="admin_unites_arbre",
        summary="Arbre des unités organisationnelles",
        responses={200: UniteArbreSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        return Response(arbre_des_unites())

    @extend_schema(
        tags=[TAG_UNITES],
        operation_id="admin_unites_creer",
        summary="Créer une unité",
        request=CreationUniteSerializer,
        responses={201: UniteSerializer, **erreurs(400, 409, r409="CODE_EXISTE.")},
    )
    def post(self, request):
        entree = CreationUniteSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        unite = services.creer_unite(par=request.user, **entree.champs_modele())
        return Response(presenter_unite(unite), status=status.HTTP_201_CREATED)


class UniteVue(APIView):
    permission_classes = [EcritureUnites]

    @extend_schema(
        tags=[TAG_UNITES],
        operation_id="admin_unite_modifier",
        summary="Modifier une unité",
        request=ModificationUniteSerializer,
        responses={200: UniteSerializer, **erreurs(400, 404, 409, r409="CODE_EXISTE.")},
    )
    def patch(self, request, unite_id):
        unite = _unite_ou_404(unite_id)
        entree = ModificationUniteSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        services.modifier_unite(unite, par=request.user, **entree.champs_modele())
        return Response(presenter_unite(unite))
