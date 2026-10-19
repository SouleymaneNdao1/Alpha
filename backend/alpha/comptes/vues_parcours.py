"""Vues de ``/api/v1/auth`` livrées par B6 (§ 4.3, § 4.5, § 4.7, § 5.2).

- activation par invitation : ``/auth/activation/{jeton}`` (+ ``mot-de-passe``,
  ``authenticator``, ``authenticator/confirmer``, ``terminer``) ;
- réenrôlement après « téléphone perdu » : ``/auth/reenrolement/{jeton}`` (mêmes étapes,
  le mot de passe ACTUEL est vérifié au lieu d'être défini) ;
- mot de passe oublié : ``/auth/mot-de-passe/oubli`` et
  ``/auth/mot-de-passe/reinitialisation/{jeton}`` (preuve MFA exigée) ;
- signalement public : ``/auth/telephone-perdu``.

Règles (§ 3.3, § 4) :
- les erreurs sont RETOURNÉES (``reponse_erreur``), jamais levées, dès qu'une écriture
  a eu lieu ; seules les erreurs de forme du corps (400 ``VALIDATION``), qui n'écrivent
  rien, sont levées ;
- chaque échec est journalisé HORS transaction, avant toute écriture d'audit dans la
  transaction de la requête (les contrôles qui peuvent échouer passent en premier) ;
- pas d'énumération de comptes : ``oubli`` et ``telephone-perdu`` répondent toujours 202 ;
- un lien e-mail est résolu par ``alpha_resoudre_jeton`` (jeton haché, ni utilisé, ni
  annulé, ni expiré, du bon objet), puis relu sous le contexte de son établissement.
"""

from __future__ import annotations

import io
import re
from contextlib import contextmanager

import pyotp
import segno
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response

from alpha.audit.models import Categorie
from alpha.audit.services import ACTEUR_ANONYME, journaliser
from alpha.core import contexte
from alpha.core.erreurs import VALIDATION, reponse_erreur
from alpha.tenancy.middleware import ETABLISSEMENT_SUSPENDU
from alpha.tenancy.middleware import MESSAGES as MESSAGES_TENANCY
from alpha.tenancy.models import Etablissement, StatutEtablissement

from . import alertes, connexion, emails, jetons, limitation, mfa, sessions, telephone
from .models import (
    AuthenticatorTOTP,
    CanalSignalement,
    EtapeJeton,
    JetonUsageUnique,
    MethodeMfa,
    MotifFinSession,
    ObjetJeton,
    StatutAuthenticator,
    StatutUtilisateur,
    Utilisateur,
)
from .resolution import resoudre_connexion, resoudre_jeton
from .serializers import (
    ErreurCodeInvalideSerializer,
    ErreurVerrouillageSerializer,
    MoiSerializer,
    donnees_moi,
)
from .serializers_parcours import (
    AccepteSerializer,
    CodesSecoursSerializer,
    CodeTotpSerializer,
    DefinitionMotDePasseSerializer,
    EnrolementAuthenticatorSerializer,
    ErreurJetonInvalideSerializer,
    InfosActivationSerializer,
    InfosReenrolementSerializer,
    InfosReinitialisationSerializer,
    MotDePasseActuelSerializer,
    OubliSerializer,
    ReinitialisationSerializer,
    TelephonePerduSerializer,
    TerminerSerializer,
)
from .vues_auth import (
    ERREUR_400,
    ERREUR_403_CSRF,
    ERREUR_429,
    VueAuth,
    _apres_echec,
    _contexte_utilisateur,
    _verrouillage,
)

JETON_INVALIDE = "JETON_INVALIDE"
ETAPE_INVALIDE = "ETAPE_INVALIDE"
CODE_INVALIDE = "CODE_INVALIDE"
MOT_DE_PASSE_INCORRECT = "MOT_DE_PASSE_INCORRECT"
MESSAGES = {
    JETON_INVALIDE: "Ce lien n'est plus valable (déjà utilisé, expiré ou remplacé). "
    "Demandez un nouveau lien.",
    ETAPE_INVALIDE: "Cette étape n'est pas disponible maintenant : reprenez le parcours "
    "depuis le lien reçu par e-mail.",
    CODE_INVALIDE: "Code de vérification invalide ou expiré.",
    MOT_DE_PASSE_INCORRECT: "Mot de passe incorrect.",
}
MOTIF_TROP_D_ESSAIS = "TROP_D_ESSAIS"
LIBELLE_AUTHENTICATOR = "Application d'authentification"
MESSAGE_ACCEPTE = (
    "Si un compte actif correspond à cette adresse, un e-mail vient de lui être envoyé."
)
MESSAGE_SIGNALEMENT = (
    "Si les informations saisies sont correctes, le signalement est enregistré : la "
    "signature est bloquée et vos sessions sont fermées. Un e-mail de confirmation vous "
    "est envoyé."
)

ORDRE_ETAPES = {
    EtapeJeton.CREE: 0,
    EtapeJeton.MDP_OK: 1,
    EtapeJeton.TOTP_EN_ATTENTE: 2,
    EtapeJeton.TOTP_OK: 3,
}

ERREUR_410 = OpenApiResponse(
    ErreurJetonInvalideSerializer, description="JETON_INVALIDE (lien expiré, utilisé ou annulé)."
)
ERREUR_409 = OpenApiResponse(
    ErreurJetonInvalideSerializer, description="ETAPE_INVALIDE (étape non disponible)."
)
ERREUR_401_CODE = OpenApiResponse(
    ErreurCodeInvalideSerializer, description="CODE_INVALIDE {tentatives_restantes}."
)
ERREUR_423 = OpenApiResponse(ErreurVerrouillageSerializer, description="COMPTE_VERROUILLE.")
TAG = "auth"


def _erreur(code: str, statut: int, details=None, message: str | None = None) -> Response:
    return reponse_erreur(code, message or MESSAGES[code], statut=statut, details=details)


def _jeton_invalide(details=None) -> Response:
    return _erreur(JETON_INVALIDE, status.HTTP_410_GONE, details)


def _etape_invalide() -> Response:
    return _erreur(ETAPE_INVALIDE, status.HTTP_409_CONFLICT)


def _validation(details: dict) -> Response:
    return reponse_erreur(VALIDATION, statut=status.HTTP_400_BAD_REQUEST, details=details)


def _messages_mdp(mot_de_passe: str, utilisateur: Utilisateur) -> list[str]:
    """Messages de la politique de mot de passe (§ 4.9) ; liste vide si conforme. Sans écriture."""
    try:
        validate_password(mot_de_passe, user=utilisateur)
    except ValidationError as erreur:
        return list(erreur.messages)
    return []


def _controle_nouveau_mdp(donnees: dict, utilisateur: Utilisateur) -> Response | None:
    if donnees["mot_de_passe"] != donnees["confirmation"]:
        return _validation({"confirmation": ["Les deux mots de passe ne correspondent pas."]})
    messages = _messages_mdp(donnees["mot_de_passe"], utilisateur)
    # Le mot de passe actuel compte parmi les « derniers » même s'il n'est pas historisé.
    if (
        not messages
        and utilisateur.has_usable_password()
        and utilisateur.check_password(donnees["mot_de_passe"])
    ):
        messages = ["Choisissez un mot de passe différent de votre mot de passe actuel."]
    if messages:
        return _validation({"mot_de_passe": messages})
    return None


def journaliser_echec_mfa(utilisateur: Utilisateur, *, parcours: str, motif: str) -> None:
    """``mfa.verification.echec`` HORS transaction (survit à toute annulation, § 3.3)."""
    journaliser(
        "mfa.verification.echec",
        Categorie.SECURITE,
        objet=("comptes.utilisateur", utilisateur.pk),
        objet_libelle=connexion.masquer_email(utilisateur.email),
        apres={"parcours": parcours, "motif": motif},
        detail=f"Code refusé · {parcours}",
        acteur=ACTEUR_ANONYME,
        hors_transaction=True,
    )


def _etablissement_ouvert(utilisateur: Utilisateur) -> bool:
    if utilisateur.est_super_admin:
        return True
    statut = (
        Etablissement.objects.filter(pk=utilisateur.etablissement_id)
        .values_list("statut", flat=True)
        .first()
    )
    return statut not in (StatutEtablissement.SUSPENDU, StatutEtablissement.ARCHIVE, None)


def _etablissement_suspendu() -> Response:
    return reponse_erreur(
        ETABLISSEMENT_SUSPENDU,
        MESSAGES_TENANCY[ETABLISSEMENT_SUSPENDU],
        statut=status.HTTP_403_FORBIDDEN,
    )


def _raison_sociale(utilisateur: Utilisateur) -> str:
    if utilisateur.est_super_admin:
        return "FYXOP"
    return (
        Etablissement.objects.filter(pk=utilisateur.etablissement_id)
        .values_list("raison_sociale", flat=True)
        .first()
        or ""
    )


def _methodes_mfa(utilisateur: Utilisateur) -> list[str]:
    methodes = []
    if AuthenticatorTOTP.objects.filter(
        utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.ACTIF
    ).exists():
        methodes.append(MethodeMfa.TOTP.value)
    if mfa.codes_secours_restants(utilisateur) > 0:
        methodes.append(MethodeMfa.CODE_SECOURS.value)
    return methodes


@contextmanager
def _sous_contexte(resolution):
    with _contexte_utilisateur(
        resolution.etablissement_id,
        resolution.etablissement_id is None,
        resolution.utilisateur_id,
    ):
        yield


def _resoudre(jeton_clair: str, objet: str):
    """Résolution du lien (sans contexte) : ``None`` si invalide ou d'un autre objet."""
    if not jeton_clair or len(jeton_clair) > 128:
        return None
    resolution = resoudre_jeton(jeton_clair)
    if resolution is None or resolution.objet != objet:
        return None
    return resolution


# --- Activation (§ 4.3) et réenrôlement (§ 4.5, étape 6) ---------------------------------------


class _VueEnrolement(VueAuth):
    """Base des étapes d'un parcours d'enrôlement par lien e-mail.

    Sous-classes : ``objet`` du jeton et ``parcours`` (``ACTIVATION`` / ``REENROLEMENT``).
    """

    objet: str = ObjetJeton.INVITATION
    parcours: str = "ACTIVATION"

    def _avec_jeton(self, jeton_clair: str, traitement, *args):
        resolution = _resoudre(jeton_clair, self.objet)
        if resolution is None:
            return _jeton_invalide()
        with _sous_contexte(resolution):
            jeton = (
                JetonUsageUnique.objects.select_for_update()
                .filter(pk=resolution.jeton_id, utilise_le__isnull=True, annule_le__isnull=True)
                .first()
            )
            utilisateur = (
                Utilisateur.objects.select_for_update().filter(pk=resolution.utilisateur_id).first()
            )
            if jeton is None or utilisateur is None or not self._compte_attendu(utilisateur):
                return _jeton_invalide()
            return traitement(jeton, utilisateur, *args)

    def _compte_attendu(self, utilisateur: Utilisateur) -> bool:
        if self.objet == ObjetJeton.INVITATION:
            return utilisateur.statut == StatutUtilisateur.INVITE
        return utilisateur.statut == StatutUtilisateur.ACTIF and utilisateur.mfa_a_reconfigurer


class _VueInfos(_VueEnrolement):
    def get(self, request, jeton):
        return self._avec_jeton(jeton, self._infos)

    def _infos(self, jeton: JetonUsageUnique, utilisateur: Utilisateur):
        donnees = {
            "prenom": utilisateur.prenom,
            "etablissement": _raison_sociale(utilisateur),
            "etape": jeton.etape,
        }
        if self.objet == ObjetJeton.INVITATION:
            from alpha.organisation.models import AffectationRole

            affectation = (
                AffectationRole.objects.actives()
                .filter(utilisateur_id=utilisateur.pk, principal=True)
                .select_related("role")
                .first()
            )
            donnees["role"] = affectation.role.libelle if affectation else ""
        return Response(donnees)


class _VueAuthenticator(_VueEnrolement):
    """Génère un secret EN_ATTENTE (l'ancien en attente est révoqué) ; QR SVG côté serveur."""

    def post(self, request, jeton):
        return self._avec_jeton(jeton, self._generer)

    def _generer(self, jeton: JetonUsageUnique, utilisateur: Utilisateur):
        if jeton.etape not in (EtapeJeton.MDP_OK, EtapeJeton.TOTP_EN_ATTENTE):
            return _etape_invalide()
        emetteur = f"ALPHA ({_raison_sociale(utilisateur)})"
        _, secret = mfa.creer_authenticator_en_attente(utilisateur, LIBELLE_AUTHENTICATOR)
        jeton.etape = EtapeJeton.TOTP_EN_ATTENTE
        jeton.save(update_fields=["etape"])
        uri = pyotp.TOTP(secret).provisioning_uri(name=utilisateur.email, issuer_name=emetteur)
        tampon = io.BytesIO()
        segno.make(uri, error="m").save(tampon, kind="svg", scale=4, xmldecl=False)
        return Response(
            {
                "qr_svg": tampon.getvalue().decode("utf-8"),
                "secret_affichable": " ".join(re.findall(".{1,4}", secret)),
                "emetteur": emetteur,
                "compte": utilisateur.email,
            }
        )


class _VueConfirmer(_VueEnrolement):
    """Premier code de l'application : Authenticator ACTIF + 10 codes de secours (une fois).

    5 codes faux : le lien est annulé (nouvelle invitation ou nouveau lien nécessaire).
    """

    def post(self, request, jeton):
        corps = CodeTotpSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        return self._avec_jeton(jeton, self._confirmer, corps.validated_data["code"])

    def _confirmer(self, jeton: JetonUsageUnique, utilisateur: Utilisateur, code: str):
        if jeton.etape != EtapeJeton.TOTP_EN_ATTENTE:
            return _etape_invalide()
        authenticator = (
            AuthenticatorTOTP.objects.select_for_update()
            .filter(utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.EN_ATTENTE)
            .order_by("-cree_le")
            .first()
        )
        if authenticator is None or not mfa.confirmer_authenticator(authenticator, code):
            essais = limitation.compter(
                f"enrolement:{self.parcours.lower()}",
                str(jeton.pk),
                fenetre_s=max(int((jeton.expire_le - timezone.now()).total_seconds()), 60),
            )
            restants = max(limitation.ESSAIS_ENROLEMENT - essais, 0)
            if restants == 0:
                jeton.annule_le = timezone.now()
                jeton.save(update_fields=["annule_le"])
                journaliser_echec_mfa(
                    utilisateur, parcours=self.parcours, motif=MOTIF_TROP_D_ESSAIS
                )
                return _jeton_invalide(
                    {"motif": MOTIF_TROP_D_ESSAIS},
                )
            journaliser_echec_mfa(utilisateur, parcours=self.parcours, motif=CODE_INVALIDE)
            return _erreur(
                CODE_INVALIDE,
                status.HTTP_401_UNAUTHORIZED,
                details={"tentatives_restantes": restants},
            )
        codes = mfa.generer_codes_secours(utilisateur)
        jeton.etape = EtapeJeton.TOTP_OK
        jeton.save(update_fields=["etape"])
        return Response({"codes_secours": codes})


class _VueTerminer(_VueEnrolement):
    def post(self, request, jeton):
        corps = TerminerSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        if request.user.is_authenticated:
            # Autre compte connecté sur ce navigateur : déconnecté AVANT toute écriture
            # d'audit dans la transaction (événement écrit hors transaction).
            connexion.fermer_session(request, MotifFinSession.DECONNEXION, hors_transaction=True)
        return self._avec_jeton(jeton, self._terminer, request)

    def _terminer(self, jeton: JetonUsageUnique, utilisateur: Utilisateur, request):
        if jeton.etape != EtapeJeton.TOTP_OK:
            return _etape_invalide()
        if connexion.est_bloque(utilisateur):
            return _verrouillage(utilisateur)
        if not _etablissement_ouvert(utilisateur):
            return _etablissement_suspendu()
        maintenant = timezone.now()
        jeton.utilise_le = maintenant
        jeton.save(update_fields=["utilise_le"])
        self._finaliser(utilisateur, maintenant)
        connexion.ouvrir_session(
            request, utilisateur, methode_mfa=MethodeMfa.TOTP, detail=self.detail_connexion
        )
        return Response(donnees_moi(utilisateur))

    detail_connexion = ""

    def _finaliser(self, utilisateur: Utilisateur, maintenant) -> None:  # pragma: no cover
        raise NotImplementedError


# Activation ---------------------------------------------------------------------------------


class _Activation:
    objet = ObjetJeton.INVITATION
    parcours = "ACTIVATION"


class VueActivationInfos(_Activation, _VueInfos):
    @extend_schema(
        operation_id="auth_activation_infos",
        summary="Activation : informations du lien d'invitation",
        description="« Bienvenue, Cheikh. L'administrateur de … vous a invité comme … ». "
        "`etape` permet de reprendre le parcours.",
        request=None,
        responses={200: InfosActivationSerializer, 410: ERREUR_410},
        tags=[TAG],
    )
    def get(self, request, jeton):
        return super().get(request, jeton)


class VueActivationMotDePasse(_Activation, _VueEnrolement):
    @extend_schema(
        operation_id="auth_activation_mot_de_passe",
        summary="Activation, étape 1 : définir le mot de passe",
        description="Politique : 12 caractères minimum (ou plus selon l'établissement), 3 "
        "catégories sur 4, ni nom ni année, différent des 5 derniers. Le compte reste INVITE "
        "tant que l'application d'authentification n'est pas confirmée.",
        request=DefinitionMotDePasseSerializer,
        responses={
            204: OpenApiResponse(description="Mot de passe enregistré."),
            400: ERREUR_400,
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        corps = DefinitionMotDePasseSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        return self._avec_jeton(jeton, self._definir, corps.validated_data)

    def _definir(self, jeton: JetonUsageUnique, utilisateur: Utilisateur, donnees: dict):
        if jeton.etape == EtapeJeton.TOTP_OK:
            return _etape_invalide()
        erreur = _controle_nouveau_mdp(donnees, utilisateur)
        if erreur is not None:
            return erreur
        from .mots_de_passe import definir_mot_de_passe

        definir_mot_de_passe(utilisateur, donnees["mot_de_passe"])
        if jeton.etape == EtapeJeton.CREE:
            jeton.etape = EtapeJeton.MDP_OK
            jeton.save(update_fields=["etape"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueActivationAuthenticator(_Activation, _VueAuthenticator):
    @extend_schema(
        operation_id="auth_activation_authenticator",
        summary="Activation, étape 2 : générer le QR code de l'application d'authentification",
        description="Nouveau secret à chaque appel (l'ancien, non confirmé, est révoqué). Le "
        "secret n'est jamais journalisé.",
        request=None,
        responses={
            200: EnrolementAuthenticatorSerializer,
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)


class VueActivationConfirmer(_Activation, _VueConfirmer):
    @extend_schema(
        operation_id="auth_activation_authenticator_confirmer",
        summary="Activation, étape 3 : confirmer avec un premier code",
        description="Renvoie 10 codes de secours, affichés UNE SEULE FOIS. Au 5e code faux, "
        "le lien est annulé (410, motif TROP_D_ESSAIS) : une nouvelle invitation est nécessaire.",
        request=CodeTotpSerializer,
        responses={
            200: CodesSecoursSerializer,
            400: ERREUR_400,
            401: ERREUR_401_CODE,
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)


class VueActivationTerminer(_Activation, _VueTerminer):
    detail_connexion = "Activation du compte · première connexion"

    @extend_schema(
        operation_id="auth_activation_terminer",
        summary="Activation, fin : compte ACTIF et session ouverte",
        description="Exige `codes_conserves: true`. Le compte devient ACTIF, le lien est "
        "consommé et la session est ouverte (cookie alpha_sid et jeton CSRF renouvelés).",
        request=TerminerSerializer,
        responses={
            200: MoiSerializer,
            400: ERREUR_400,
            403: OpenApiResponse(
                description="ETABLISSEMENT_SUSPENDU ou CSRF_INVALIDE.",
                response=ErreurJetonInvalideSerializer,
            ),
            409: ERREUR_409,
            410: ERREUR_410,
            423: ERREUR_423,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)

    def _finaliser(self, utilisateur: Utilisateur, maintenant) -> None:
        avant = {"statut": utilisateur.statut}
        utilisateur.statut = StatutUtilisateur.ACTIF
        utilisateur.active_le = maintenant
        utilisateur.save(update_fields=["statut", "active_le", "modifie_le"])
        journaliser(
            "utilisateur.active",
            Categorie.MODIFICATION,
            objet=utilisateur,
            objet_libelle=utilisateur.email,
            avant=avant,
            apres={"statut": utilisateur.statut, "active_le": maintenant},
            detail="Compte activé par l'utilisateur",
            acteur=utilisateur,
        )
        journaliser(
            "mfa.active",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            apres={"codes_secours": mfa.codes_secours_restants(utilisateur)},
            detail="Application d'authentification configurée · codes de secours remis",
            acteur=utilisateur,
        )


# Réenrôlement --------------------------------------------------------------------------------


class _Reenrolement:
    objet = ObjetJeton.REENROLEMENT_MFA
    parcours = "REENROLEMENT"


class VueReenrolementInfos(_Reenrolement, _VueInfos):
    @extend_schema(
        operation_id="auth_reenrolement_infos",
        summary="Réenrôlement : informations du lien",
        request=None,
        responses={200: InfosReenrolementSerializer, 410: ERREUR_410},
        tags=[TAG],
    )
    def get(self, request, jeton):
        return super().get(request, jeton)


class VueReenrolementMotDePasse(_Reenrolement, _VueEnrolement):
    @extend_schema(
        operation_id="auth_reenrolement_mot_de_passe",
        summary="Réenrôlement, étape 1 : vérifier le mot de passe actuel",
        description="Un échec compte comme un échec de connexion (verrouillage après N échecs).",
        request=MotDePasseActuelSerializer,
        responses={
            204: OpenApiResponse(description="Mot de passe vérifié."),
            400: ERREUR_400,
            401: OpenApiResponse(
                ErreurCodeInvalideSerializer,
                description="MOT_DE_PASSE_INCORRECT {tentatives_restantes}.",
            ),
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
            423: ERREUR_423,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        corps = MotDePasseActuelSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        return self._avec_jeton(jeton, self._verifier, corps.validated_data["mot_de_passe"])

    def _verifier(self, jeton: JetonUsageUnique, utilisateur: Utilisateur, mot_de_passe: str):
        if jeton.etape == EtapeJeton.TOTP_OK:
            return _etape_invalide()
        if connexion.est_bloque(utilisateur):
            make_password(mot_de_passe)
            connexion.journaliser_echec(
                connexion.MOTIF_VERROUILLE, email=utilisateur.email, utilisateur=utilisateur
            )
            return _verrouillage(utilisateur)
        if not utilisateur.check_password(mot_de_passe):
            regles = connexion.regles_pour(utilisateur)
            verrouille = _apres_echec(
                utilisateur, regles, motif="REENROLEMENT_MOT_DE_PASSE", email=utilisateur.email
            )
            if verrouille:
                return _verrouillage(utilisateur)
            return _erreur(
                MOT_DE_PASSE_INCORRECT,
                status.HTTP_401_UNAUTHORIZED,
                details={
                    "tentatives_restantes": connexion.tentatives_restantes(utilisateur, regles)
                },
            )
        if jeton.etape == EtapeJeton.CREE:
            jeton.etape = EtapeJeton.MDP_OK
            jeton.save(update_fields=["etape"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueReenrolementAuthenticator(_Reenrolement, _VueAuthenticator):
    @extend_schema(
        operation_id="auth_reenrolement_authenticator",
        summary="Réenrôlement, étape 2 : QR code du nouveau téléphone",
        request=None,
        responses={
            200: EnrolementAuthenticatorSerializer,
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)


class VueReenrolementConfirmer(_Reenrolement, _VueConfirmer):
    @extend_schema(
        operation_id="auth_reenrolement_authenticator_confirmer",
        summary="Réenrôlement, étape 3 : confirmer avec un premier code",
        description="Renvoie 10 NOUVEAUX codes de secours (les anciens ont été invalidés), "
        "affichés une seule fois. Au 5e code faux, le lien est annulé.",
        request=CodeTotpSerializer,
        responses={
            200: CodesSecoursSerializer,
            400: ERREUR_400,
            401: ERREUR_401_CODE,
            403: ERREUR_403_CSRF,
            409: ERREUR_409,
            410: ERREUR_410,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)


class VueReenrolementTerminer(_Reenrolement, _VueTerminer):
    detail_connexion = "Réenrôlement de l'application d'authentification · connexion"

    @extend_schema(
        operation_id="auth_reenrolement_terminer",
        summary="Réenrôlement, fin : signature débloquée et session ouverte",
        request=TerminerSerializer,
        responses={
            200: MoiSerializer,
            400: ERREUR_400,
            403: OpenApiResponse(
                description="ETABLISSEMENT_SUSPENDU ou CSRF_INVALIDE.",
                response=ErreurJetonInvalideSerializer,
            ),
            409: ERREUR_409,
            410: ERREUR_410,
            423: ERREUR_423,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        return super().post(request, jeton)

    def _finaliser(self, utilisateur: Utilisateur, maintenant) -> None:
        avant = telephone._figer(utilisateur)
        utilisateur.signature_bloquee = False
        utilisateur.mfa_a_reconfigurer = False
        utilisateur.echecs_connexion = 0
        utilisateur.save(
            update_fields=[
                "signature_bloquee",
                "mfa_a_reconfigurer",
                "echecs_connexion",
                "modifie_le",
            ]
        )
        journaliser(
            "mfa.reenrole",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            avant=avant,
            apres={
                **telephone._figer(utilisateur),
                "codes_secours": mfa.codes_secours_restants(utilisateur),
            },
            detail="Nouvelle application d'authentification · signature débloquée",
            acteur=utilisateur,
        )
        emails.programmer(
            "mfa_reenrole",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(maintenant),
        )


# --- Mot de passe oublié (§ 4.7) ---------------------------------------------------------------


def _limites(paires) -> Response | None:
    for espace, identifiant, (limite, fenetre) in paires:
        attente = limitation.consommer(espace, identifiant, limite=limite, fenetre_s=fenetre)
        if attente is not None:
            return limitation.reponse_trop_de_requetes(attente)
    return None


class VueOubli(VueAuth):
    @extend_schema(
        operation_id="auth_mot_de_passe_oubli",
        summary="Mot de passe oublié : demander un lien",
        description="Réponse 202 identique que l'adresse corresponde ou non à un compte. Si le "
        "compte est ACTIF : lien valable `validite_reinit_mdp_min` minutes (les liens précédents "
        "sont annulés). Limites : 3/h par e-mail, 10/h par IP.",
        request=OubliSerializer,
        responses={202: AccepteSerializer, 400: ERREUR_400, 403: ERREUR_403_CSRF, 429: ERREUR_429},
        tags=[TAG],
    )
    def post(self, request):
        corps = OubliSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        email = corps.validated_data["email"].strip()
        trop = _limites(
            (
                ("oubli:ip", contexte.ip() or "-", limitation.OUBLI_PAR_IP),
                ("oubli:email", email.lower(), limitation.OUBLI_PAR_EMAIL),
            )
        )
        if trop is not None:
            return trop
        resolution = resoudre_connexion(email)
        if resolution is not None:
            with _contexte_utilisateur(
                resolution.etablissement_id, resolution.est_super_admin, resolution.utilisateur_id
            ):
                self._emettre(resolution.utilisateur_id)
        return Response({"message": MESSAGE_ACCEPTE}, status=status.HTTP_202_ACCEPTED)

    def _emettre(self, utilisateur_id) -> None:
        utilisateur = Utilisateur.objects.select_for_update().filter(pk=utilisateur_id).first()
        if utilisateur is None or utilisateur.statut != StatutUtilisateur.ACTIF:
            return
        jeton, clair = jetons.emettre_reinit_mdp(utilisateur)
        validite = jetons.validite_reinit_mdp(utilisateur)
        journaliser(
            "auth.mdp.oubli_demande",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            apres={"expire_le": jeton.expire_le},
            detail="Demande de réinitialisation du mot de passe · lien envoyé",
            acteur=ACTEUR_ANONYME,
        )
        emails.programmer(
            "reinitialisation_mdp",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(),
            lien=emails.lien(f"/reinitialisation/{clair}"),
            validite_min=int(validite.total_seconds() // 60),
        )


class _VueReinitialisation(VueAuth):
    def _avec_jeton(self, jeton_clair: str, traitement, *args):
        resolution = _resoudre(jeton_clair, ObjetJeton.REINIT_MDP)
        if resolution is None:
            return _jeton_invalide()
        with _sous_contexte(resolution):
            jeton = (
                JetonUsageUnique.objects.select_for_update()
                .filter(pk=resolution.jeton_id, utilise_le__isnull=True, annule_le__isnull=True)
                .first()
            )
            utilisateur = (
                Utilisateur.objects.select_for_update().filter(pk=resolution.utilisateur_id).first()
            )
            if (
                jeton is None
                or utilisateur is None
                or utilisateur.statut != StatutUtilisateur.ACTIF
            ):
                return _jeton_invalide()
            return traitement(jeton, utilisateur, *args)


class VueReinitialisation(_VueReinitialisation):
    @extend_schema(
        operation_id="auth_mot_de_passe_reinitialisation_infos",
        summary="Réinitialisation : informations du lien",
        request=None,
        responses={200: InfosReinitialisationSerializer, 410: ERREUR_410},
        tags=[TAG],
    )
    def get(self, request, jeton):
        return self._avec_jeton(jeton, self._infos)

    def _infos(self, jeton, utilisateur: Utilisateur):
        return Response(
            {
                "email_masque": connexion.masquer_email(utilisateur.email),
                "methodes": _methodes_mfa(utilisateur),
            }
        )

    @extend_schema(
        operation_id="auth_mot_de_passe_reinitialisation",
        summary="Réinitialisation : nouveau mot de passe, avec preuve MFA",
        description="Preuve MFA obligatoire (`code` TOTP OU `code_secours`) : l'accès à la "
        "seule boîte e-mail ne suffit pas. Succès : toutes les sessions sont révoquées, le "
        "verrouillage temporaire est levé, e-mail de confirmation. Un code faux compte comme "
        "un échec de connexion.",
        request=ReinitialisationSerializer,
        responses={
            204: OpenApiResponse(description="Mot de passe modifié ; se reconnecter."),
            400: ERREUR_400,
            401: ERREUR_401_CODE,
            403: ERREUR_403_CSRF,
            410: ERREUR_410,
            423: ERREUR_423,
        },
        tags=[TAG],
    )
    def post(self, request, jeton):
        corps = ReinitialisationSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        return self._avec_jeton(jeton, self._reinitialiser, corps.validated_data)

    def _reinitialiser(self, jeton: JetonUsageUnique, utilisateur: Utilisateur, donnees: dict):
        # 1. Contrôles sans écriture : politique du mot de passe AVANT de consommer la preuve MFA.
        erreur = _controle_nouveau_mdp(donnees, utilisateur)
        if erreur is not None:
            return erreur
        if connexion.est_bloque(utilisateur):
            connexion.journaliser_echec(
                connexion.MOTIF_VERROUILLE, email=utilisateur.email, utilisateur=utilisateur
            )
            return _verrouillage(utilisateur)
        # 2. Preuve MFA (un échec compte dans le verrouillage, journalisé hors transaction).
        if donnees.get("code"):
            methode = MethodeMfa.TOTP
            valide = mfa.verifier_totp(utilisateur, donnees["code"])
        else:
            methode = MethodeMfa.CODE_SECOURS
            valide = mfa.consommer_code_secours(utilisateur, donnees["code_secours"])
        if not valide:
            regles = connexion.regles_pour(utilisateur)
            verrouille = connexion.enregistrer_echec(utilisateur, regles)
            journaliser_echec_mfa(utilisateur, parcours="REINIT_MDP", motif=CODE_INVALIDE)
            if verrouille:
                connexion.journaliser_verrouillage(utilisateur)
                alertes.compte_verrouille(utilisateur, utilisateur.verrouille_jusqua)
                return _verrouillage(utilisateur)
            return _erreur(
                CODE_INVALIDE,
                status.HTTP_401_UNAUTHORIZED,
                details={
                    "tentatives_restantes": connexion.tentatives_restantes(utilisateur, regles)
                },
            )
        # 3. Effets (audit dans la transaction).
        from .mots_de_passe import definir_mot_de_passe

        maintenant = timezone.now()
        definir_mot_de_passe(utilisateur, donnees["mot_de_passe"])
        utilisateur.echecs_connexion = 0
        utilisateur.verrouille_jusqua = None
        utilisateur.save(update_fields=["echecs_connexion", "verrouille_jusqua", "modifie_le"])
        jeton.utilise_le = maintenant
        jeton.save(update_fields=["utilise_le"])
        revoquees = sessions.revoquer_sessions(utilisateur, MotifFinSession.MDP_CHANGE)
        if methode == MethodeMfa.CODE_SECOURS:
            restants = mfa.codes_secours_restants(utilisateur)
            journaliser(
                "mfa.code_secours_utilise",
                Categorie.SECURITE,
                objet=("comptes.utilisateur", utilisateur.pk),
                objet_libelle=utilisateur.nom_complet,
                apres={"restants": restants},
                detail=f"Réinitialisation du mot de passe par code de secours · {restants} "
                "code(s) restant(s)",
                acteur=utilisateur,
            )
            alertes.code_secours_utilise(utilisateur, restants)
        journaliser(
            "auth.mdp.reinitialise",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            apres={"methode_mfa": methode, "sessions_revoquees": revoquees},
            detail="Mot de passe réinitialisé · toutes les sessions révoquées",
            acteur=utilisateur,
        )
        emails.programmer(
            "mdp_modifie", utilisateur.email, prenom=utilisateur.prenom, heure=emails.heure()
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Téléphone perdu, page publique (§ 4.5, étape 1) -------------------------------------------


class VueTelephonePerdu(VueAuth):
    @extend_schema(
        operation_id="auth_telephone_perdu",
        summary="Signaler la perte de son téléphone (page publique)",
        description="Réponse 202 identique dans tous les cas (aucune information sur "
        "l'existence du compte). Mot de passe correct : signature bloquée, application "
        "d'authentification suspendue, sessions révoquées, tâche pour les administrateurs, "
        "e-mails. Mot de passe faux : un échec de connexion est compté, rien d'autre. "
        "Limite : 3/h par IP.",
        request=TelephonePerduSerializer,
        responses={
            202: AccepteSerializer,
            400: ERREUR_400,
            403: ERREUR_403_CSRF,
            429: ERREUR_429,
        },
        tags=[TAG],
    )
    def post(self, request):
        corps = TelephonePerduSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        email = corps.validated_data["email"].strip()
        mot_de_passe = corps.validated_data["mot_de_passe"]
        trop = _limites(
            (("telephone:ip", contexte.ip() or "-", limitation.TELEPHONE_PERDU_PAR_IP),)
        )
        if trop is not None:
            return trop
        accepte = Response({"message": MESSAGE_SIGNALEMENT}, status=status.HTTP_202_ACCEPTED)
        resolution = resoudre_connexion(email)
        if resolution is None or resolution.est_super_admin:
            make_password(mot_de_passe)  # temps constant
            connexion.journaliser_echec(connexion.MOTIF_EMAIL_INCONNU, email=email, plateforme=True)
            return accepte
        with _contexte_utilisateur(resolution.etablissement_id, False, resolution.utilisateur_id):
            self._signaler(resolution.utilisateur_id, email, mot_de_passe)
        return accepte

    def _signaler(self, utilisateur_id, email: str, mot_de_passe: str) -> None:
        utilisateur = Utilisateur.objects.select_for_update().filter(pk=utilisateur_id).first()
        if utilisateur is None:
            make_password(mot_de_passe)
            return
        if utilisateur.has_usable_password():
            mot_de_passe_ok = utilisateur.check_password(mot_de_passe)
        else:
            make_password(mot_de_passe)
            mot_de_passe_ok = False
        if connexion.est_bloque(utilisateur):
            connexion.journaliser_echec(
                connexion.MOTIF_VERROUILLE, email=email, utilisateur=utilisateur
            )
            return
        if utilisateur.statut != StatutUtilisateur.ACTIF:
            connexion.journaliser_echec(
                connexion.MOTIF_INACTIF, email=email, utilisateur=utilisateur
            )
            return
        if not mot_de_passe_ok:
            regles = connexion.regles_pour(utilisateur)
            _apres_echec(utilisateur, regles, motif="TELEPHONE_PERDU_MOT_DE_PASSE", email=email)
            return
        telephone.signaler(utilisateur, canal=CanalSignalement.PAGE_PUBLIQUE, acteur=utilisateur)
