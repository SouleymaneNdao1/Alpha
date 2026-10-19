"""Vues de « Mon compte » (``/api/v1/moi``, § 4.4, § 4.5, § 4.7, § 4.8, § 5.3 ; tâche B9).

Permission « Session » (utilisateur d'établissement, MFA faite) ; le super-admin FYXOP
est refusé. Chacun n'agit que sur SON compte : sessions, Authenticator, codes.

Règles (§ 3.3, § 4.9) :
- le changement de mot de passe, le changement d'Authenticator et la régénération des
  codes de secours exigent un step-up TOTP (``mfa.verifier_step_up`` : pas consommé,
  5 essais/min, refus journalisés HORS transaction) ;
- les erreurs sont RETOURNÉES dès qu'un contrôle a pu écrire (échec compté, audit) ;
  seules les erreurs de forme du corps (400 ``VALIDATION``), sans écriture, sont levées ;
- les contrôles qui peuvent échouer passent AVANT toute écriture d'audit dans la
  transaction de la requête ;
- aucun secret dans les réponses, sauf les codes de secours au moment de leur
  génération et le secret du nouvel Authenticator (QR et saisie manuelle).

Expiration du mot de passe (P3) : quand ``Moi.mot_de_passe_expire`` est vrai, seules
les vues marquées ``autorise_mot_de_passe_expire`` restent ouvertes (lecture du profil
et de la sécurité, changement du mot de passe, téléphone perdu) ; les autres routes
d'établissement répondent 403 ``MOT_DE_PASSE_EXPIRE`` (``alpha.core.permissions.Session``).
"""

from __future__ import annotations

import datetime
import io
import re

import pyotp
import segno
from django.contrib.auth import HASH_SESSION_KEY, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core.erreurs import INTROUVABLE, VALIDATION, reponse_erreur
from alpha.core.permissions import Session
from alpha.core.schema_erreurs import ErreurSerializer, erreurs
from alpha.tenancy.models import Etablissement

from . import administration, connexion, emails, limitation, mfa, sessions, telephone
from .models import (
    AuthenticatorTOTP,
    CanalSignalement,
    MotifFinSession,
    SessionAppareil,
    SignalementTelephonePerdu,
    StatutAuthenticator,
    StatutSignalement,
    Utilisateur,
)
from .serializers import (
    ErreurCodeInvalideSerializer,
    ErreurTropDeRequetesSerializer,
    ErreurVerrouillageSerializer,
    MoiSerializer,
    donnees_moi,
)
from .serializers_moi import (
    ChangementAuthenticatorSerializer,
    ChangementMotDePasseSerializer,
    ConfirmationAuthenticatorSerializer,
    ProfilSerializer,
    RevocationMesSessionsSerializer,
    SecuriteSerializer,
    SessionMoiSerializer,
    StepUpSerializer,
)
from .serializers_parcours import (
    AccepteSerializer,
    CodesSecoursSerializer,
    EnrolementAuthenticatorSerializer,
)
from .vues_auth import _apres_echec, _verrouillage

TAG = "Mon compte"

CODE_INVALIDE = "CODE_INVALIDE"
MOT_DE_PASSE_INCORRECT = "MOT_DE_PASSE_INCORRECT"
AUTHENTICATOR_INDISPONIBLE = "AUTHENTICATOR_INDISPONIBLE"
AUCUN_CHANGEMENT_EN_COURS = "AUCUN_CHANGEMENT_EN_COURS"
SESSION_COURANTE = "SESSION_COURANTE"
MESSAGES = {
    CODE_INVALIDE: "Code de vérification invalide ou expiré.",
    MOT_DE_PASSE_INCORRECT: "Mot de passe actuel incorrect.",
    AUTHENTICATOR_INDISPONIBLE: "Aucune application d'authentification active sur votre "
    "compte. Utilisez « Téléphone perdu » ou contactez votre administrateur.",
    AUCUN_CHANGEMENT_EN_COURS: "Aucun changement d'application en cours, ou délai dépassé. "
    "Recommencez depuis le début.",
    SESSION_COURANTE: "Pour fermer la session de cet appareil, utilisez « Se déconnecter ».",
}
MOTIF_MOT_DE_PASSE = "MON_COMPTE_MOT_DE_PASSE"
LIBELLE_AUTHENTICATOR = "Application d'authentification"
MESSAGE_SIGNALEMENT = (
    "Signalement enregistré : la signature est bloquée et toutes vos sessions sont fermées, "
    "y compris celle-ci. Un administrateur va vérifier votre identité."
)

#: Changement d'Authenticator en cours (clé de la session Django) et sa durée.
CLE_CHANGEMENT = "changement_authenticator"
DUREE_CHANGEMENT = datetime.timedelta(minutes=10)
ESSAIS_CHANGEMENT = 5

ERREUR_401_CODE = OpenApiResponse(
    ErreurCodeInvalideSerializer,
    description="CODE_INVALIDE (step-up refusé) ou non authentifié.",
)
ERREUR_429 = OpenApiResponse(
    ErreurTropDeRequetesSerializer, description="TROP_DE_REQUETES (step-up : 5 essais/min)."
)


def _erreur(code: str, statut: int, details=None) -> Response:
    return reponse_erreur(code, MESSAGES[code], statut=statut, details=details)


def _validation(details: dict) -> Response:
    return reponse_erreur(VALIDATION, statut=status.HTTP_400_BAD_REQUEST, details=details)


def _step_up(utilisateur: Utilisateur, code: str) -> Response | None:
    """Step-up TOTP (§ 4.9) : ``None`` si accepté, sinon la réponse d'erreur à RETOURNER.

    Le refus est journalisé hors transaction par ``mfa.verifier_step_up``.
    """
    resultat, attente = mfa.verifier_step_up(utilisateur, code)
    if resultat == mfa.STEP_UP_OK:
        return None
    if resultat == mfa.STEP_UP_TROP_DE_REQUETES:
        return limitation.reponse_trop_de_requetes(attente)
    return _erreur(CODE_INVALIDE, status.HTTP_401_UNAUTHORIZED)


def _moi_verrouille(request) -> Utilisateur:
    return Utilisateur.objects.select_for_update().get(pk=request.user.pk)


def _session_courante(request) -> SessionAppareil | None:
    cle = request.session.session_key
    return sessions.session_par_cle(cle) if cle else None


class VueMoi(APIView):
    permission_classes = [Session]


# --- Profil -------------------------------------------------------------------------------------


class MoiVue(VueMoi):
    autorise_mot_de_passe_expire = True

    @extend_schema(
        tags=[TAG],
        operation_id="moi_lire",
        summary="Mon profil (objet Moi)",
        responses={200: MoiSerializer, **erreurs()},
    )
    def get(self, request):
        return Response(MoiSerializer(donnees_moi(request.user)).data)

    @extend_schema(
        tags=[TAG],
        operation_id="moi_modifier",
        summary="Modifier mon profil",
        description="Prénom, nom, téléphone mobile (E.164) et langue. L'e-mail n'est pas "
        "modifiable : s'il est envoyé, 400 VALIDATION. Journalisé (utilisateur.modifie).",
        request=ProfilSerializer,
        responses={200: MoiSerializer, **erreurs(400)},
    )
    def patch(self, request):
        corps = ProfilSerializer(data=request.data, partial=True)
        corps.is_valid(raise_exception=True)
        utilisateur = administration.modifier(
            _moi_verrouille(request), par=request.user, **corps.validated_data
        )
        return Response(MoiSerializer(donnees_moi(utilisateur)).data)


# --- Mot de passe -----------------------------------------------------------------------------


class MotDePasseVue(VueMoi):
    autorise_mot_de_passe_expire = True

    @extend_schema(
        tags=[TAG],
        operation_id="moi_mot_de_passe",
        summary="Changer mon mot de passe",
        description="Ordre des contrôles : verrouillage (423), mot de passe actuel (401 "
        "MOT_DE_PASSE_INCORRECT {tentatives_restantes}, compté dans le verrouillage), politique "
        "et historique de l'établissement (400 VALIDATION sur `nouveau` ou `confirmation`), puis "
        "step-up TOTP (`code`, 401 CODE_INVALIDE, 429). Succès : les AUTRES sessions sont "
        "révoquées, la session courante est conservée, e-mail d'alerte. Seule action ouverte, "
        "avec la lecture du profil, quand le mot de passe a expiré (P3).",
        request=ChangementMotDePasseSerializer,
        responses={
            204: OpenApiResponse(description="Mot de passe modifié."),
            400: OpenApiResponse(ErreurSerializer, description="VALIDATION."),
            401: OpenApiResponse(
                ErreurCodeInvalideSerializer,
                description="MOT_DE_PASSE_INCORRECT {tentatives_restantes} ou CODE_INVALIDE.",
            ),
            403: OpenApiResponse(ErreurSerializer, description="Permission refusée."),
            423: OpenApiResponse(ErreurVerrouillageSerializer, description="COMPTE_VERROUILLE."),
            429: ERREUR_429,
        },
    )
    def post(self, request):
        corps = ChangementMotDePasseSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        donnees = corps.validated_data
        utilisateur = _moi_verrouille(request)

        # 1. Contrôles (les échecs sont comptés et journalisés hors transaction).
        if connexion.est_bloque(utilisateur):
            return _verrouillage(utilisateur)
        if not utilisateur.check_password(donnees["actuel"]):
            regles = connexion.regles_pour(utilisateur)
            if _apres_echec(utilisateur, regles, motif=MOTIF_MOT_DE_PASSE, email=utilisateur.email):
                return _verrouillage(utilisateur)
            return _erreur(
                MOT_DE_PASSE_INCORRECT,
                status.HTTP_401_UNAUTHORIZED,
                details={
                    "tentatives_restantes": connexion.tentatives_restantes(utilisateur, regles)
                },
            )
        # Politique AVANT le step-up (le code n'est pas consommé pour rien).
        if donnees["nouveau"] != donnees["confirmation"]:
            return _validation({"confirmation": ["Les deux mots de passe ne correspondent pas."]})
        if donnees["nouveau"] == donnees["actuel"]:
            return _validation(
                {"nouveau": ["Choisissez un mot de passe différent de votre mot de passe actuel."]}
            )
        try:
            validate_password(donnees["nouveau"], user=utilisateur)
        except ValidationError as erreur:
            return _validation({"nouveau": list(erreur.messages)})
        refus = _step_up(utilisateur, donnees["code"])
        if refus is not None:
            return refus

        # 2. Effets.
        from .mots_de_passe import definir_mot_de_passe

        definir_mot_de_passe(utilisateur, donnees["nouveau"])
        utilisateur.echecs_connexion = 0
        utilisateur.save(update_fields=["echecs_connexion", "modifie_le"])
        # La session courante reste valable avec le nouveau mot de passe (sans changer de clé :
        # la session d'appareil est indexée par l'empreinte de la clé).
        request.session[HASH_SESSION_KEY] = utilisateur.get_session_auth_hash()
        courante = _session_courante(request)
        revoquees = sessions.revoquer_sessions(
            utilisateur, MotifFinSession.MDP_CHANGE, sauf=courante.id if courante else None
        )
        journaliser(
            "auth.mdp.modifie",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            apres={"sessions_revoquees": revoquees},
            detail="Mot de passe modifié depuis Mon compte · autres sessions révoquées",
            acteur=utilisateur,
        )
        emails.programmer(
            "mdp_modifie",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(),
            depuis_mon_compte=True,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Sécurité -------------------------------------------------------------------------------------


class SecuriteVue(VueMoi):
    autorise_mot_de_passe_expire = True

    @extend_schema(
        tags=[TAG],
        operation_id="moi_securite",
        summary="État de sécurité de mon compte",
        description="Application d'authentification, nombre de codes de secours restants "
        "(jamais les codes), signature, signalement en cours, date du mot de passe.",
        responses={200: SecuriteSerializer, **erreurs()},
    )
    def get(self, request):
        utilisateur = request.user
        authenticator = (
            AuthenticatorTOTP.objects.filter(
                utilisateur_id=utilisateur.pk,
                statut__in=[StatutAuthenticator.ACTIF, StatutAuthenticator.SUSPENDU],
            )
            .order_by("-confirme_le")
            .first()
        )
        if authenticator is None:
            etat = {"statut": "NON_CONFIGUREE", "libelle": "", "active_le": None}
        else:
            etat = {
                "statut": "ACTIVE"
                if authenticator.statut == StatutAuthenticator.ACTIF
                else "SUSPENDUE",
                "libelle": authenticator.libelle,
                "active_le": authenticator.confirme_le,
            }
        signalement = (
            SignalementTelephonePerdu.objects.filter(
                utilisateur_id=utilisateur.pk, statut=StatutSignalement.OUVERT
            )
            .values("statut", "signale_le")
            .first()
        )
        donnees = {
            "authenticator": etat,
            "codes_secours_restants": mfa.codes_secours_restants(utilisateur),
            "signature_bloquee": utilisateur.signature_bloquee,
            "signalement": signalement,
            "mdp_modifie_le": utilisateur.mdp_modifie_le,
            "mot_de_passe_expire": connexion.mot_de_passe_expire(
                utilisateur, connexion.regles_pour(utilisateur)
            ),
        }
        return Response(SecuriteSerializer(donnees).data)


# --- Changement d'Authenticator (§ 4.5, « changement de téléphone sans perte ») ------------------


def _qr(utilisateur: Utilisateur, secret: str) -> dict:
    raison_sociale = (
        Etablissement.objects.filter(pk=utilisateur.etablissement_id)
        .values_list("raison_sociale", flat=True)
        .first()
        or ""
    )
    emetteur = f"ALPHA ({raison_sociale})"
    uri = pyotp.TOTP(secret).provisioning_uri(name=utilisateur.email, issuer_name=emetteur)
    tampon = io.BytesIO()
    segno.make(uri, error="m").save(tampon, kind="svg", scale=4, xmldecl=False)
    return {
        "qr_svg": tampon.getvalue().decode("utf-8"),
        "secret_affichable": " ".join(re.findall(".{1,4}", secret)),
        "emetteur": emetteur,
        "compte": utilisateur.email,
    }


def _changement_en_cours(request) -> str | None:
    """Identifiant de l'Authenticator EN_ATTENTE lancé par CETTE session, s'il n'a pas expiré."""
    etat = request.session.get(CLE_CHANGEMENT)
    if not isinstance(etat, dict):
        return None
    try:
        expire = datetime.datetime.fromisoformat(etat["expire"])
    except (KeyError, TypeError, ValueError):
        return None
    if expire <= timezone.now():
        return None
    return etat.get("id")


class ChangementAuthenticatorVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_authenticator_changement",
        summary="Changer de téléphone, étape 1 : nouveau QR code",
        description="Step-up avec le code de l'application ACTUELLE (`code_actuel`). Crée une "
        "nouvelle application EN ATTENTE, liée à cette session pendant 10 minutes ; l'actuelle "
        "reste active jusqu'à la confirmation. Le secret n'est renvoyé qu'ici (QR et saisie "
        "manuelle) ; il n'est jamais journalisé. 409 AUTHENTICATOR_INDISPONIBLE si aucune "
        "application active (téléphone perdu : passer par le signalement).",
        request=ChangementAuthenticatorSerializer,
        responses={
            200: EnrolementAuthenticatorSerializer,
            **erreurs(400, 409, r409="AUTHENTICATOR_INDISPONIBLE."),
            401: ERREUR_401_CODE,
            429: ERREUR_429,
        },
    )
    def post(self, request):
        corps = ChangementAuthenticatorSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        utilisateur = _moi_verrouille(request)
        if mfa.authenticator_actif(utilisateur) is None:
            return _erreur(AUTHENTICATOR_INDISPONIBLE, status.HTTP_409_CONFLICT)
        refus = _step_up(utilisateur, corps.validated_data["code_actuel"])
        if refus is not None:
            return refus
        authenticator, secret = mfa.creer_authenticator_en_attente(
            utilisateur, LIBELLE_AUTHENTICATOR
        )
        request.session[CLE_CHANGEMENT] = {
            "id": str(authenticator.pk),
            "expire": (timezone.now() + DUREE_CHANGEMENT).isoformat(),
        }
        return Response(_qr(utilisateur, secret))


class ConfirmerChangementAuthenticatorVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_authenticator_changement_confirmer",
        summary="Changer de téléphone, étape 2 : confirmer avec le nouveau code",
        description="Premier code de la NOUVELLE application : l'ancienne est révoquée, la "
        "nouvelle devient active ; les codes de secours sont conservés. E-mail d'alerte, audit "
        "mfa.change. 5 codes faux : le changement est annulé (recommencer l'étape 1). 409 "
        "AUCUN_CHANGEMENT_EN_COURS si l'étape 1 n'a pas été faite dans cette session ou date de "
        "plus de 10 minutes.",
        request=ConfirmationAuthenticatorSerializer,
        responses={
            204: OpenApiResponse(description="Nouvelle application active."),
            **erreurs(400, 409, r409="AUCUN_CHANGEMENT_EN_COURS."),
            401: OpenApiResponse(
                ErreurCodeInvalideSerializer, description="CODE_INVALIDE {tentatives_restantes}."
            ),
        },
    )
    def post(self, request):
        corps = ConfirmationAuthenticatorSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        utilisateur = _moi_verrouille(request)
        identifiant = _changement_en_cours(request)
        authenticator = (
            AuthenticatorTOTP.objects.select_for_update()
            .filter(
                pk=identifiant, utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.EN_ATTENTE
            )
            .first()
            if identifiant
            else None
        )
        if authenticator is None:
            request.session.pop(CLE_CHANGEMENT, None)
            return _erreur(AUCUN_CHANGEMENT_EN_COURS, status.HTTP_409_CONFLICT)
        ancien = mfa.authenticator_actif(utilisateur)
        if not mfa.confirmer_authenticator(authenticator, corps.validated_data["code_nouveau"]):
            essais = limitation.compter(
                "changement_authenticator",
                str(authenticator.pk),
                fenetre_s=int(DUREE_CHANGEMENT.total_seconds()),
            )
            restants = max(ESSAIS_CHANGEMENT - essais, 0)
            if restants == 0:
                authenticator.statut = StatutAuthenticator.REVOQUE
                authenticator.revoque_le = timezone.now()
                authenticator.save(update_fields=["statut", "revoque_le"])
                request.session.pop(CLE_CHANGEMENT, None)
            journaliser(
                "mfa.verification.echec",
                Categorie.SECURITE,
                objet=("comptes.utilisateur", utilisateur.pk),
                objet_libelle=utilisateur.nom_complet,
                apres={"parcours": "CHANGEMENT", "motif": CODE_INVALIDE},
                detail="Code refusé · changement d'application d'authentification",
                acteur=utilisateur,
                hors_transaction=True,
            )
            return _erreur(
                CODE_INVALIDE,
                status.HTTP_401_UNAUTHORIZED,
                details={"tentatives_restantes": restants},
            )
        request.session.pop(CLE_CHANGEMENT, None)
        courante = _session_courante(request)
        journaliser(
            "mfa.change",
            Categorie.SECURITE,
            objet=authenticator,
            objet_libelle=utilisateur.nom_complet,
            avant={"authenticator_id": ancien.pk if ancien else None},
            apres={"authenticator_id": authenticator.pk, "libelle": authenticator.libelle},
            detail="Application d'authentification remplacée (codes de secours conservés)",
            acteur=utilisateur,
        )
        emails.programmer(
            "authenticator_change",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(),
            appareil=courante.appareil if courante else "appareil inconnu",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Codes de secours (§ 4.4) ---------------------------------------------------------------


class CodesSecoursVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_codes_secours",
        summary="Régénérer mes codes de secours",
        description="Step-up TOTP (`code`). 10 nouveaux codes, affichés UNE SEULE FOIS ; les "
        "anciens sont invalidés. Audit mfa.codes_regeneres (sans les codes).",
        request=StepUpSerializer,
        responses={
            200: CodesSecoursSerializer,
            **erreurs(400),
            401: ERREUR_401_CODE,
            429: ERREUR_429,
        },
    )
    def post(self, request):
        corps = StepUpSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        utilisateur = _moi_verrouille(request)
        refus = _step_up(utilisateur, corps.validated_data["code"])
        if refus is not None:
            return refus
        codes = mfa.generer_codes_secours(utilisateur)
        journaliser(
            "mfa.codes_regeneres",
            Categorie.SECURITE,
            objet=("comptes.utilisateur", utilisateur.pk),
            objet_libelle=utilisateur.nom_complet,
            apres={"nombre": len(codes)},
            detail="Codes de secours régénérés (les précédents sont invalidés)",
            acteur=utilisateur,
        )
        return Response({"codes_secours": codes})


# --- Téléphone perdu (§ 4.5) ------------------------------------------------------------------


class TelephonePerduVue(VueMoi):
    autorise_mot_de_passe_expire = True

    @extend_schema(
        tags=[TAG],
        operation_id="moi_telephone_perdu",
        summary="Signaler la perte de mon téléphone",
        description="Signature bloquée, application d'authentification suspendue, TOUTES les "
        "sessions révoquées (y compris celle-ci : l'utilisateur est déconnecté), tâche pour les "
        "administrateurs, e-mails. Idempotent si un signalement est déjà ouvert.",
        request=None,
        responses={202: AccepteSerializer, **erreurs()},
    )
    def post(self, request):
        telephone.signaler(
            _moi_verrouille(request), canal=CanalSignalement.MON_COMPTE, acteur=request.user
        )
        logout(request)
        return Response({"message": MESSAGE_SIGNALEMENT}, status=status.HTTP_202_ACCEPTED)


# --- Sessions et appareils (§ 4.8) ------------------------------------------------------------


def _sessions_actives(utilisateur: Utilisateur):
    maintenant = timezone.now()
    regles = connexion.regles_pour(utilisateur)
    return SessionAppareil.objects.filter(
        utilisateur_id=utilisateur.pk,
        revoque_le__isnull=True,
        expire_le__gt=maintenant,
        derniere_activite__gt=maintenant - regles.inactivite,
    )


class SessionsVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_sessions",
        summary="Mes appareils et sessions actives",
        responses={200: SessionMoiSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        courante = _session_courante(request)
        lignes = _sessions_actives(request.user).order_by("-derniere_activite", "id")
        return Response(
            SessionMoiSerializer(
                [
                    {
                        "id": s.id,
                        "appareil": s.appareil,
                        "ip": s.ip,
                        "methode_mfa": s.methode_mfa,
                        "cree_le": s.cree_le,
                        "derniere_activite": s.derniere_activite,
                        "courante": courante is not None and s.id == courante.id,
                    }
                    for s in lignes
                ],
                many=True,
            ).data
        )


def _journaliser_revocation(utilisateur, *, objet, objet_libelle, nombre: int, detail: str):
    journaliser(
        "auth.session.revoquee",
        Categorie.CONNEXION,
        objet=objet,
        objet_libelle=objet_libelle,
        apres={"motif": MotifFinSession.REVOCATION_UTILISATEUR, "sessions_revoquees": nombre},
        detail=detail,
        acteur=utilisateur,
    )


class SessionVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_session_revoquer",
        summary="Fermer une de mes sessions (autre appareil)",
        description="404 si la session n'existe pas, n'est plus active ou appartient à un autre "
        "utilisateur ; 409 SESSION_COURANTE pour la session de cet appareil (utiliser la "
        "déconnexion).",
        request=None,
        responses={
            204: OpenApiResponse(description="Session fermée."),
            **erreurs(404, 409, r409="SESSION_COURANTE."),
        },
    )
    def delete(self, request, session_id):
        session = (
            SessionAppareil.objects.select_for_update()
            .filter(pk=session_id, utilisateur_id=request.user.pk, revoque_le__isnull=True)
            .first()
        )
        if session is None:
            return reponse_erreur(INTROUVABLE, statut=status.HTTP_404_NOT_FOUND)
        courante = _session_courante(request)
        if courante is not None and courante.id == session.id:
            return _erreur(SESSION_COURANTE, status.HTTP_409_CONFLICT)
        sessions.revoquer_session(session, MotifFinSession.REVOCATION_UTILISATEUR)
        _journaliser_revocation(
            request.user,
            objet=session,
            objet_libelle=session.appareil,
            nombre=1,
            detail=f"Session fermée par l'utilisateur · {session.appareil}",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class RevoquerAutresSessionsVue(VueMoi):
    @extend_schema(
        tags=[TAG],
        operation_id="moi_sessions_revoquer_autres",
        summary="Fermer toutes mes autres sessions",
        description="Toutes les sessions actives sauf celle de cet appareil.",
        request=None,
        responses={200: RevocationMesSessionsSerializer, **erreurs()},
    )
    def post(self, request):
        courante = _session_courante(request)
        nombre = sessions.revoquer_sessions(
            request.user,
            MotifFinSession.REVOCATION_UTILISATEUR,
            sauf=courante.id if courante else None,
        )
        if nombre:
            _journaliser_revocation(
                request.user,
                objet=("comptes.utilisateur", request.user.pk),
                objet_libelle=request.user.nom_complet,
                nombre=nombre,
                detail=f"Autres sessions fermées par l'utilisateur ({nombre})",
            )
        return Response({"revoquees": nombre})
