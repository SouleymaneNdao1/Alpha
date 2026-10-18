"""API d'administration des comptes : ``/api/v1/admin/utilisateurs…`` et ``/admin/affectations…``
(§ 5.5, tâche B7).

Toutes les routes exigent ``Perm("admin.utilisateurs")`` : utilisateur d'établissement
connecté, titulaire de la permission (le super-admin FYXOP est refusé, § 3.8). Les objets
sont lus par les managers filtrés sur l'établissement courant : un identifiant d'un autre
établissement donne 404, jamais 403 (§ 5).
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit.models import EvenementAudit
from alpha.core import contexte
from alpha.core.erreurs import VALIDATION, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.models import AffectationRole
from alpha.organisation.permissions import Perm

from . import administration
from .models import StatutUtilisateur, Utilisateur
from .serializers_admin import (
    LIBELLES_ACTIONS,
    AffectationSerializer,
    EvenementAuditSerializer,
    InvitationRenvoyeeSerializer,
    InvitationSerializer,
    ModificationUtilisateurSerializer,
    NouvelleAffectationSerializer,
    PageUtilisateursSerializer,
    RevocationSessionsSerializer,
    SuspensionReponseSerializer,
    SuspensionSerializer,
    UtilisateurDetailSerializer,
    presenter_affectation,
    presenter_detail,
    presenter_evenement,
    presenter_liste,
)

TAG = "Administration · utilisateurs"
PermUtilisateurs = Perm(CodePermission.ADMIN_UTILISATEURS)

#: Types d'objets couverts par l'historique « Utilisateurs et comptes ».
OBJETS_HISTORIQUE = ("comptes.utilisateur", "organisation.affectationrole")
LIMITE_HISTORIQUE_DEFAUT = 3
LIMITE_HISTORIQUE_MAX = 50


def utilisateur_ou_404(utilisateur_id) -> Utilisateur:
    """Utilisateur de l'établissement courant, sinon 404."""
    utilisateur = (
        Utilisateur.objects.select_related("responsable").filter(id=utilisateur_id).first()
    )
    if utilisateur is None:
        raise NotFound()
    return utilisateur


class VueAdminUtilisateurs(APIView):
    permission_classes = [PermUtilisateurs]


class UtilisateursVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateurs_liste",
        summary="Liste des utilisateurs de l'établissement",
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, description="Nom, prénom ou e-mail."),
            OpenApiParameter("role_id", OpenApiTypes.UUID, description="Titulaires de ce rôle."),
            OpenApiParameter("statut", OpenApiTypes.STR, enum=StatutUtilisateur.values),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("taille", OpenApiTypes.INT, description="25 par défaut, 100 au plus."),
        ],
        responses={200: PageUtilisateursSerializer, **erreurs(400)},
    )
    def get(self, request):
        qs = Utilisateur.objects.order_by("nom", "prenom", "email")
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(email__icontains=q))
        statut = request.query_params.get("statut")
        if statut:
            if statut not in StatutUtilisateur.values:
                return _erreur_parametre("statut", "Statut inconnu.")
            qs = qs.filter(statut=statut)
        role_id = request.query_params.get("role_id")
        if role_id:
            try:
                role_uuid = uuid.UUID(role_id)
            except ValueError:
                return _erreur_parametre("role_id", "Identifiant invalide.")
            titulaires = AffectationRole.objects.en_cours().filter(role_id=role_uuid)
            qs = qs.filter(id__in=titulaires.values("utilisateur_id"))
        paginateur = PaginationPage()
        page = paginateur.paginate_queryset(qs, request, view=self)
        return paginateur.get_paginated_response(presenter_liste(page))

    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateurs_inviter",
        summary="Inviter un utilisateur",
        description="Crée le compte en statut INVITE, son affectation principale et un lien "
        "d'activation valable `validite_invitation_h` heures (e-mail envoyé après validation).",
        request=InvitationSerializer,
        responses={
            201: UtilisateurDetailSerializer,
            **erreurs(400, 409, r400="VALIDATION ou ROLE_HORS_CATALOGUE.", r409="EMAIL_EXISTE."),
        },
    )
    def post(self, request):
        entree = InvitationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        utilisateur = administration.inviter(
            par=request.user,
            email=d["email"],
            prenom=d["prenom"],
            nom=d["nom"],
            role_id=d["role_id"],
            unite=d.get("unite_id"),
            responsable=d.get("responsable_id"),
            telephone_mobile=d.get("telephone_mobile"),
        )
        return Response(presenter_detail(utilisateur), status=status.HTTP_201_CREATED)


def _erreur_parametre(champ: str, message: str) -> Response:
    return reponse_erreur(VALIDATION, details={champ: [message]})


class UtilisateurVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_detail",
        summary="Fiche d'un utilisateur",
        responses={200: UtilisateurDetailSerializer, **erreurs(404)},
    )
    def get(self, request, utilisateur_id):
        return Response(presenter_detail(utilisateur_ou_404(utilisateur_id)))

    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_modifier",
        summary="Modifier un utilisateur",
        request=ModificationUtilisateurSerializer,
        responses={200: UtilisateurDetailSerializer, **erreurs(400, 404)},
    )
    def patch(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        entree = ModificationUtilisateurSerializer(
            data=request.data, partial=True, context={"utilisateur": utilisateur}
        )
        entree.is_valid(raise_exception=True)
        administration.modifier(utilisateur, par=request.user, **entree.champs_modele())
        return Response(presenter_detail(utilisateur))


class AffectationsUtilisateurVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_affecter",
        summary="Attribuer un rôle à un utilisateur",
        description="`principal: true` : l'affectation principale précédente devient secondaire.",
        request=NouvelleAffectationSerializer,
        responses={
            201: AffectationSerializer,
            **erreurs(400, 404, 409, r409="AFFECTATION_EXISTE (même rôle, même périmètre)."),
        },
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        entree = NouvelleAffectationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        affectation = administration.ajouter_affectation(
            utilisateur,
            par=request.user,
            role_id=d["role_id"],
            unite=d.get("unite_id"),
            principal=d["principal"],
        )
        return Response(presenter_affectation(affectation), status=status.HTTP_201_CREATED)


class TerminerAffectationVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_affectation_terminer",
        summary="Retirer un rôle (terminer une affectation)",
        request=None,
        responses={
            200: AffectationSerializer,
            **erreurs(404, 409, r409="DERNIER_ADMINISTRATEUR ou AFFECTATION_TERMINEE."),
        },
    )
    def post(self, request, affectation_id):
        affectation = (
            AffectationRole.objects.select_related("role", "unite", "utilisateur")
            .filter(id=affectation_id)
            .first()
        )
        if affectation is None:
            raise NotFound()
        administration.terminer_affectation(affectation, par=request.user)
        return Response(presenter_affectation(affectation))


class SuspendreVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_suspendre",
        summary="Suspendre un utilisateur",
        description="Le compte ne peut plus se connecter ; ses sessions sont révoquées.",
        request=SuspensionSerializer,
        responses={
            200: SuspensionReponseSerializer,
            **erreurs(400, 404, 409, r409="DERNIER_ADMINISTRATEUR ou STATUT_INVALIDE."),
        },
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        entree = SuspensionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        revoquees = administration.suspendre(
            utilisateur, par=request.user, motif=entree.validated_data["motif"]
        )
        return Response({**presenter_detail(utilisateur), "sessions_revoquees": revoquees})


class ReactiverVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_reactiver",
        summary="Réactiver un utilisateur suspendu",
        request=None,
        responses={200: UtilisateurDetailSerializer, **erreurs(404, 409, r409="STATUT_INVALIDE.")},
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        administration.reactiver(utilisateur, par=request.user)
        return Response(presenter_detail(utilisateur))


class DeverrouillerVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_deverrouiller",
        summary="Déverrouiller un utilisateur",
        description="Remet à zéro les échecs de connexion, le verrouillage temporaire et le "
        "blocage administrateur (3 verrouillages en 24 h).",
        request=None,
        responses={200: UtilisateurDetailSerializer, **erreurs(404)},
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        administration.deverrouiller(utilisateur, par=request.user)
        return Response(presenter_detail(utilisateur))


class RenvoyerInvitationVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_renvoyer_invitation",
        summary="Renvoyer l'invitation",
        description="Annule le lien précédent et envoie un nouveau lien d'activation.",
        request=None,
        responses={
            202: InvitationRenvoyeeSerializer,
            **erreurs(404, 409, r409="UTILISATEUR_NON_INVITE."),
        },
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        jeton = administration.renvoyer_invitation(utilisateur, par=request.user)
        return Response({"expire_le": jeton.expire_le}, status=status.HTTP_202_ACCEPTED)


class RevoquerSessionsVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateur_revoquer_sessions",
        summary="Révoquer toutes les sessions d'un utilisateur",
        request=None,
        responses={200: RevocationSessionsSerializer, **erreurs(404)},
    )
    def post(self, request, utilisateur_id):
        utilisateur = utilisateur_ou_404(utilisateur_id)
        revoquees = administration.revoquer_sessions(utilisateur, par=request.user)
        return Response({"revoquees": revoquees})


class HistoriqueVue(VueAdminUtilisateurs):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_utilisateurs_historique",
        summary="Dernières actions d'administration sur les comptes",
        parameters=[
            OpenApiParameter(
                "limite",
                OpenApiTypes.INT,
                description=f"{LIMITE_HISTORIQUE_DEFAUT} par défaut, "
                f"{LIMITE_HISTORIQUE_MAX} au plus.",
            )
        ],
        responses={200: EvenementAuditSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        brut = request.query_params.get("limite", str(LIMITE_HISTORIQUE_DEFAUT))
        try:
            limite = int(brut)
        except ValueError:
            limite = 0
        if not 1 <= limite <= LIMITE_HISTORIQUE_MAX:
            return _erreur_parametre(
                "limite", f"Entier attendu entre 1 et {LIMITE_HISTORIQUE_MAX}."
            )
        evenements = EvenementAudit.objects.filter(
            etablissement_id=contexte.tenant_courant(),
            objet_type__in=OBJETS_HISTORIQUE,
            action__in=list(LIBELLES_ACTIONS),
        ).order_by("-seq")[:limite]
        return Response([presenter_evenement(e) for e in evenements])
