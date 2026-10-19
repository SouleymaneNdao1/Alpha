"""Paramètres de sécurité de l'établissement : ``/api/v1/admin/parametres-securite`` (§ 5.5, B7).

Décisions P2 et P3 (§ 10) : durées de session, politique de mot de passe, verrouillage et
validité des liens sont réglables par établissement. Bornes appliquées par l'API (plus
strictes que les contraintes ``CHECK`` de la base, qui restent la dernière barrière) :
les planchers de la politique de mot de passe validée (12 caractères, 5 anciens mots de
passe interdits) et de la conservation du journal (10 ans) ne peuvent pas être abaissés.

``PATCH`` exige ``admin.securite`` + un code TOTP de confirmation (« StepUp », § 4.9),
vérifié par ``alpha.comptes.raccordements.verifier_code_step_up`` (B5 : pas TOTP consommé,
refus journalisé ; la vue RETOURNE le 401). Audit : ``parametres.securite.modifies``
(champs modifiés seulement).
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.comptes import raccordements
from alpha.core.erreurs import reponse_erreur
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.permissions import Perm

from .models import ParametresEtablissement

CODE_INVALIDE = "CODE_INVALIDE"

#: (minimum, maximum) de chaque réglage numérique modifiable.
BORNES: dict[str, tuple[int, int]] = {
    "inactivite_session_min": (5, 60),
    "duree_max_session_h": (1, 24),
    "mdp_longueur_min": (12, 64),
    "mdp_historique": (5, 24),
    "mdp_expiration_jours": (30, 365),
    "tentatives_max": (3, 10),
    "verrouillage_min": (5, 1440),
    "verrouillages_max_24h": (1, 10),
    "validite_invitation_h": (1, 168),
    "validite_reinit_mdp_min": (10, 120),
    "retention_audit_annees": (10, 50),
}


def _entier(champ: str, **options) -> serializers.IntegerField:
    minimum, maximum = BORNES[champ]
    return serializers.IntegerField(min_value=minimum, max_value=maximum, **options)


class ParametresSecuriteSerializer(serializers.Serializer):
    """``ParametresEtablissement`` exposé à l'administrateur (lecture)."""

    inactivite_session_min = serializers.IntegerField()
    duree_max_session_h = serializers.IntegerField()
    mdp_longueur_min = serializers.IntegerField()
    mdp_historique = serializers.IntegerField()
    mdp_expiration_jours = serializers.IntegerField(allow_null=True)
    tentatives_max = serializers.IntegerField()
    verrouillage_min = serializers.IntegerField()
    verrouillages_max_24h = serializers.IntegerField()
    validite_invitation_h = serializers.IntegerField()
    validite_reinit_mdp_min = serializers.IntegerField()
    retention_audit_annees = serializers.IntegerField()
    email_controle_interne = serializers.EmailField(allow_blank=True)
    modules_actifs = serializers.ListField(child=serializers.CharField())
    modifie_le = serializers.DateTimeField()


class ModificationParametresSerializer(serializers.Serializer):
    """Corps de ``PATCH /admin/parametres-securite`` : réglages facultatifs + ``code`` TOTP."""

    code = serializers.RegexField(
        r"^[0-9]{6}$",
        write_only=True,
        error_messages={"invalid": "Code à 6 chiffres attendu."},
        help_text="Code TOTP de confirmation (step-up).",
    )
    inactivite_session_min = _entier("inactivite_session_min", required=False)
    duree_max_session_h = _entier("duree_max_session_h", required=False)
    mdp_longueur_min = _entier("mdp_longueur_min", required=False)
    mdp_historique = _entier("mdp_historique", required=False)
    mdp_expiration_jours = _entier("mdp_expiration_jours", required=False, allow_null=True)
    tentatives_max = _entier("tentatives_max", required=False)
    verrouillage_min = _entier("verrouillage_min", required=False)
    verrouillages_max_24h = _entier("verrouillages_max_24h", required=False)
    validite_invitation_h = _entier("validite_invitation_h", required=False)
    validite_reinit_mdp_min = _entier("validite_reinit_mdp_min", required=False)
    retention_audit_annees = _entier("retention_audit_annees", required=False)
    email_controle_interne = serializers.EmailField(
        max_length=254, required=False, allow_blank=True
    )


def presenter_parametres(parametres: ParametresEtablissement) -> dict:
    return {
        **{champ: getattr(parametres, champ) for champ in ParametresEtablissement.AUDIT_CHAMPS},
        "modules_actifs": list(parametres.modules_actifs),
        "modifie_le": parametres.modifie_le,
    }


def _parametres_ou_404(*, verrou: bool = False) -> ParametresEtablissement:
    qs = ParametresEtablissement.objects.all()
    if verrou:
        qs = qs.select_for_update()
    parametres = qs.first()
    if parametres is None:
        raise NotFound()
    return parametres


TAG = "Administration · sécurité"


class ParametresSecuriteVue(APIView):
    permission_classes = [Perm(CodePermission.ADMIN_SECURITE)]

    @extend_schema(
        tags=[TAG],
        operation_id="admin_parametres_securite_lire",
        summary="Paramètres de sécurité de l'établissement",
        responses={200: ParametresSecuriteSerializer, **erreurs(404)},
    )
    def get(self, request):
        return Response(presenter_parametres(_parametres_ou_404()))

    @extend_schema(
        tags=[TAG],
        operation_id="admin_parametres_securite_modifier",
        summary="Modifier les paramètres de sécurité (code TOTP requis)",
        description="Bornes : "
        + " ; ".join(f"{c} {mini}–{maxi}" for c, (mini, maxi) in BORNES.items())
        + " (mdp_expiration_jours : null = pas d'expiration).",
        request=ModificationParametresSerializer,
        responses={
            200: ParametresSecuriteSerializer,
            **erreurs(400, 404, r400="VALIDATION (bornes)."),
        },
    )
    def patch(self, request):
        # Pas de « partial » : « code » est obligatoire, les réglages sont tous facultatifs.
        entree = ModificationParametresSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = dict(entree.validated_data)
        code = donnees.pop("code")
        if not raccordements.verifier_code_step_up(request.user.pk, code):
            # RETOURNÉE, pas levée (§ 3.3) : le refus journalisé et le compteur de débit
            # ne dépendent pas de la transaction de la vue.
            return reponse_erreur(CODE_INVALIDE, "Code de confirmation invalide.", statut=401)
        parametres = _parametres_ou_404(verrou=True)
        modifies = [c for c, v in donnees.items() if getattr(parametres, c) != v]
        if modifies:
            avant = extraire_champs(parametres, modifies)
            for champ in modifies:
                setattr(parametres, champ, donnees[champ])
            parametres.save(update_fields=[*modifies, "modifie_le"])
            journaliser(
                "parametres.securite.modifies",
                Categorie.PARAMETRAGE,
                objet=parametres,
                objet_libelle="Paramètres de sécurité",
                avant=avant,
                apres=extraire_champs(parametres, modifies),
                acteur=request.user,
            )
        return Response(presenter_parametres(parametres))
