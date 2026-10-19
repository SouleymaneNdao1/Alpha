"""Vues de ``/api/v1/auth`` : CSRF, session, connexion, MFA, déconnexion (§ 4.2, § 4.6, § 5.2).

Règle du § 3.3 : ces vues RETOURNENT leurs réponses d'erreur (401, 403, 423, 429)
au lieu de lever une exception, et les échecs d'authentification sont
journalisés hors transaction (``journaliser(..., hors_transaction=True)``) :
l'événement survit à toute annulation. Les erreurs de forme du corps (400
``VALIDATION``), qui n'écrivent rien, sont levées normalement.

Toute méthode non sûre exige le jeton CSRF (``SessionCsrfObligatoire``), même
pour un visiteur anonyme (protection contre le « login CSRF »).
"""

from __future__ import annotations

import uuid

from django.contrib.auth.hashers import make_password
from django.middleware.csrf import get_token
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core import contexte
from alpha.core.erreurs import NON_AUTHENTIFIE, reponse_erreur
from alpha.core.permissions import Anonyme, EstAuthentifie
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.middleware import ETABLISSEMENT_SUSPENDU
from alpha.tenancy.middleware import MESSAGES as MESSAGES_TENANCY
from alpha.tenancy.models import Etablissement, StatutEtablissement

from . import alertes, connexion, limitation, mfa
from .authentification import SessionCsrfObligatoire
from .models import (
    AuthenticatorTOTP,
    MethodeMfa,
    MotifFinSession,
    StatutAuthenticator,
    StatutUtilisateur,
    Utilisateur,
)
from .resolution import resoudre_connexion
from .serializers import (
    ConnexionReussieSerializer,
    ConnexionSerializer,
    ErreurCodeInvalideSerializer,
    ErreurSerializer,
    ErreurTropDeRequetesSerializer,
    ErreurVerrouillageSerializer,
    EtapeConnexionSerializer,
    MfaSerializer,
    MoiSerializer,
    donnees_moi,
)

IDENTIFIANTS_INVALIDES = "IDENTIFIANTS_INVALIDES"
CODE_INVALIDE = "CODE_INVALIDE"
PREAUTH_EXPIREE = "PREAUTH_EXPIREE"
COMPTE_VERROUILLE = "COMPTE_VERROUILLE"
MESSAGES = {
    IDENTIFIANTS_INVALIDES: "Adresse e-mail ou mot de passe incorrect.",
    CODE_INVALIDE: "Code de vérification invalide ou expiré.",
    PREAUTH_EXPIREE: "Votre demande de connexion a expiré. Saisissez de nouveau votre "
    "adresse e-mail et votre mot de passe.",
    COMPTE_VERROUILLE: "Votre compte est verrouillé suite à plusieurs tentatives échouées.",
}
ETAPE_MFA = "MFA_REQUIS"
ETAPE_REENROLEMENT = "REENROLEMENT_REQUIS"

ERREUR_401 = OpenApiResponse(ErreurSerializer, description="Non authentifié.")
ERREUR_403_CSRF = OpenApiResponse(ErreurSerializer, description="CSRF_INVALIDE.")
ERREUR_400 = OpenApiResponse(ErreurSerializer, description="VALIDATION (corps invalide).")
ERREUR_429 = OpenApiResponse(
    ErreurTropDeRequetesSerializer, description="TROP_DE_REQUETES (en-tête Retry-After)."
)


def _erreur(code: str, statut: int, details=None) -> Response:
    return reponse_erreur(code, MESSAGES[code], statut=statut, details=details)


def _identifiants_invalides() -> Response:
    return _erreur(IDENTIFIANTS_INVALIDES, status.HTTP_401_UNAUTHORIZED)


def _verrouillage(utilisateur: Utilisateur) -> Response:
    message = MESSAGES[COMPTE_VERROUILLE]
    if utilisateur.bloque_par_admin:
        message += " Seul un administrateur de votre établissement peut le débloquer."
    else:
        heure = timezone.localtime(utilisateur.verrouille_jusqua).strftime("%H:%M")
        message += f" Réessayez après {heure}."
    return reponse_erreur(
        COMPTE_VERROUILLE,
        message,
        statut=status.HTTP_423_LOCKED,
        details={
            "jusqua": None if utilisateur.bloque_par_admin else utilisateur.verrouille_jusqua,
            "deblocage_administrateur": utilisateur.bloque_par_admin,
        },
    )


def _contexte_utilisateur(etablissement_id, est_super_admin: bool, utilisateur_id):
    if est_super_admin:
        return contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=utilisateur_id)
    return contexte_tenant(etablissement_id, utilisateur_id=utilisateur_id)


def _apres_echec(utilisateur: Utilisateur, regles, *, motif: str, email: str) -> bool:
    """Compte l'échec, journalise (hors transaction) et prévient si verrouillage."""
    verrouille = connexion.enregistrer_echec(utilisateur, regles)
    connexion.journaliser_echec(motif, email=email, utilisateur=utilisateur)
    if verrouille:
        connexion.journaliser_verrouillage(utilisateur)
        alertes.compte_verrouille(utilisateur, utilisateur.verrouille_jusqua)
    return verrouille


class VueAuth(APIView):
    """Base des vues de ``/auth`` : session + CSRF obligatoire sur les méthodes non sûres."""

    authentication_classes = [SessionCsrfObligatoire]
    permission_classes = [Anonyme]


class VueCsrf(VueAuth):
    @extend_schema(
        operation_id="auth_csrf",
        summary="Pose le cookie CSRF (alpha_csrf)",
        description="À appeler avant tout POST : pose le cookie alpha_csrf, dont la valeur "
        "doit être renvoyée dans l'en-tête X-CSRFToken.",
        request=None,
        responses={204: OpenApiResponse(description="Cookie alpha_csrf posé.")},
        tags=["auth"],
    )
    def get(self, request):
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueSession(VueAuth):
    @extend_schema(
        operation_id="auth_session",
        summary="Session courante (« Rester connecté » : prolonge l'inactivité)",
        description="Renvoie Moi si une session (mot de passe + MFA) est ouverte. Compte "
        "comme une activité (bouton « Rester connecté »), sauf avec l'en-tête X-Alpha-Fond: 1. "
        "401 NON_AUTHENTIFIE sans session, 401 SESSION_EXPIREE si la session vient d'expirer.",
        request=None,
        responses={200: MoiSerializer, 401: ERREUR_401},
        tags=["auth"],
    )
    def get(self, request):
        if not request.user.is_authenticated:
            return reponse_erreur(NON_AUTHENTIFIE, statut=status.HTTP_401_UNAUTHORIZED)
        return Response(MoiSerializer(donnees_moi(request.user)).data)


class VueConnexion(VueAuth):
    @extend_schema(
        operation_id="auth_connexion",
        summary="Connexion, étape 1 : e-mail et mot de passe",
        description="Vérifie le mot de passe et ouvre une pré-authentification de 5 min "
        "(aucune session). Limites : 10/min par IP, 20/h par e-mail. Même réponse 401 pour un "
        "e-mail inconnu, un mot de passe faux, un compte inactif ou verrouillé ; 403 "
        "ETABLISSEMENT_SUSPENDU seulement si le mot de passe est correct.",
        request=ConnexionSerializer,
        responses={
            200: EtapeConnexionSerializer,
            400: ERREUR_400,
            401: OpenApiResponse(ErreurSerializer, description="IDENTIFIANTS_INVALIDES."),
            403: OpenApiResponse(
                ErreurSerializer, description="ETABLISSEMENT_SUSPENDU ou CSRF_INVALIDE."
            ),
            429: ERREUR_429,
        },
        tags=["auth"],
    )
    def post(self, request):
        corps = ConnexionSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        email = corps.validated_data["email"].strip()
        mot_de_passe = corps.validated_data["mot_de_passe"]

        for espace, identifiant, (limite, fenetre) in (
            ("connexion:ip", contexte.ip() or "-", limitation.CONNEXION_PAR_IP),
            ("connexion:email", email.lower(), limitation.CONNEXION_PAR_EMAIL),
        ):
            attente = limitation.consommer(espace, identifiant, limite=limite, fenetre_s=fenetre)
            if attente is not None:
                return limitation.reponse_trop_de_requetes(attente)

        if request.user.is_authenticated:
            # Hors transaction : un échec journalisé ensuite dans la même chaîne ne doit
            # pas attendre le verrou de chaîne pris par cet événement.
            connexion.fermer_session(request, MotifFinSession.DECONNEXION, hors_transaction=True)
        request.session.pop(connexion.CLE_PREAUTH, None)

        resolution = resoudre_connexion(email)
        if resolution is None:
            make_password(mot_de_passe)  # temps constant : hachage Argon2 factice
            connexion.journaliser_echec(connexion.MOTIF_EMAIL_INCONNU, email=email, plateforme=True)
            return _identifiants_invalides()

        with _contexte_utilisateur(
            resolution.etablissement_id, resolution.est_super_admin, resolution.utilisateur_id
        ):
            return self._verifier(request, resolution.utilisateur_id, email, mot_de_passe)

    def _verifier(self, request, utilisateur_id: uuid.UUID, email: str, mot_de_passe: str):
        utilisateur = Utilisateur.objects.select_for_update().filter(pk=utilisateur_id).first()
        if utilisateur is None:  # supprimé entre-temps
            make_password(mot_de_passe)
            connexion.journaliser_echec(connexion.MOTIF_EMAIL_INCONNU, email=email, plateforme=True)
            return _identifiants_invalides()
        regles = connexion.regles_pour(utilisateur)

        if utilisateur.has_usable_password():
            mot_de_passe_ok = utilisateur.check_password(mot_de_passe)
        else:
            make_password(mot_de_passe)
            mot_de_passe_ok = False

        if connexion.est_bloque(utilisateur):
            connexion.journaliser_echec(
                connexion.MOTIF_VERROUILLE, email=email, utilisateur=utilisateur
            )
            return _identifiants_invalides()
        if utilisateur.statut != StatutUtilisateur.ACTIF:
            connexion.journaliser_echec(
                connexion.MOTIF_INACTIF, email=email, utilisateur=utilisateur
            )
            return _identifiants_invalides()
        if not mot_de_passe_ok:
            _apres_echec(utilisateur, regles, motif=connexion.MOTIF_MOT_DE_PASSE, email=email)
            return _identifiants_invalides()

        if not utilisateur.est_super_admin:
            statut = (
                Etablissement.objects.filter(pk=utilisateur.etablissement_id)
                .values_list("statut", flat=True)
                .first()
            )
            if statut in (StatutEtablissement.SUSPENDU, StatutEtablissement.ARCHIVE, None):
                connexion.journaliser_echec(
                    connexion.MOTIF_SUSPENDU, email=email, utilisateur=utilisateur
                )
                return reponse_erreur(
                    ETABLISSEMENT_SUSPENDU,
                    MESSAGES_TENANCY[ETABLISSEMENT_SUSPENDU],
                    statut=status.HTTP_403_FORBIDDEN,
                )

        totp = AuthenticatorTOTP.objects.filter(
            utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.ACTIF
        ).exists()
        codes = mfa.codes_secours_restants(utilisateur) > 0
        methodes = [m for m, ok in (("TOTP", totp), ("CODE_SECOURS", codes)) if ok]
        if utilisateur.mfa_a_reconfigurer or not methodes:
            return Response({"etape": ETAPE_REENROLEMENT, "methodes": []})
        request.session[connexion.CLE_PREAUTH] = connexion.nouvel_etat_preauth(utilisateur)
        return Response({"etape": ETAPE_MFA, "methodes": methodes})


class VueMfa(VueAuth):
    @extend_schema(
        operation_id="auth_mfa",
        summary="Connexion, étape 2 : code TOTP ou code de secours",
        description="Corps : {code} (6 chiffres) OU {code_secours}. Limite : 5/min par "
        "session. Succès : session ouverte (cookie alpha_sid renouvelé, jeton CSRF renouvelé : "
        "relire le cookie alpha_csrf).",
        request=MfaSerializer,
        responses={
            200: ConnexionReussieSerializer,
            400: ERREUR_400,
            401: OpenApiResponse(
                ErreurCodeInvalideSerializer,
                description="CODE_INVALIDE {tentatives_restantes} ou PREAUTH_EXPIREE.",
            ),
            403: ERREUR_403_CSRF,
            423: OpenApiResponse(
                ErreurVerrouillageSerializer, description="COMPTE_VERROUILLE {jusqua}."
            ),
            429: ERREUR_429,
        },
        tags=["auth"],
    )
    def post(self, request):
        preauth = connexion.lire_preauth(request)
        if preauth is None:
            request.session.pop(connexion.CLE_PREAUTH, None)
            return _erreur(PREAUTH_EXPIREE, status.HTTP_401_UNAUTHORIZED)

        limite, fenetre = limitation.MFA_PAR_SESSION
        attente = limitation.consommer(
            "mfa:session",
            request.session.session_key or contexte.ip() or "-",
            limite=limite,
            fenetre_s=fenetre,
        )
        if attente is not None:
            return limitation.reponse_trop_de_requetes(attente)

        corps = MfaSerializer(data=request.data)
        corps.is_valid(raise_exception=True)

        with _contexte_utilisateur(
            preauth.get("tenant_id"),
            preauth.get("scope") == contexte.SCOPE_PLATFORM,
            preauth["user_id"],
        ):
            return self._verifier(request, preauth, corps.validated_data)

    def _verifier(self, request, preauth: dict, donnees: dict):
        utilisateur = Utilisateur.objects.select_for_update().filter(pk=preauth["user_id"]).first()
        if utilisateur is None or utilisateur.statut != StatutUtilisateur.ACTIF:
            request.session.pop(connexion.CLE_PREAUTH, None)
            return _erreur(PREAUTH_EXPIREE, status.HTTP_401_UNAUTHORIZED)
        if connexion.est_bloque(utilisateur):
            request.session.pop(connexion.CLE_PREAUTH, None)
            connexion.journaliser_echec(
                connexion.MOTIF_VERROUILLE, email=utilisateur.email, utilisateur=utilisateur
            )
            return _verrouillage(utilisateur)
        regles = connexion.regles_pour(utilisateur)

        if donnees.get("code"):
            methode = MethodeMfa.TOTP
            valide = mfa.verifier_totp(utilisateur, donnees["code"])
        else:
            methode = MethodeMfa.CODE_SECOURS
            valide = mfa.consommer_code_secours(utilisateur, donnees["code_secours"])

        if not valide:
            verrouille = _apres_echec(
                utilisateur, regles, motif=connexion.MOTIF_MFA, email=utilisateur.email
            )
            if verrouille:
                request.session.pop(connexion.CLE_PREAUTH, None)
                return _verrouillage(utilisateur)
            preauth["essais_mfa"] = int(preauth.get("essais_mfa", 0)) + 1
            request.session[connexion.CLE_PREAUTH] = preauth
            return _erreur(
                CODE_INVALIDE,
                status.HTTP_401_UNAUTHORIZED,
                details={
                    "tentatives_restantes": connexion.tentatives_restantes(utilisateur, regles)
                },
            )

        restants = mfa.codes_secours_restants(utilisateur)
        if methode == MethodeMfa.CODE_SECOURS:
            journaliser(
                "mfa.code_secours_utilise",
                Categorie.SECURITE,
                objet=("comptes.utilisateur", utilisateur.pk),
                objet_libelle=utilisateur.nom_complet,
                apres={"restants": restants},
                detail=f"Connexion par code de secours · {restants} code(s) restant(s)",
                acteur=utilisateur,
            )
            alertes.code_secours_utilise(utilisateur, restants)
        connexion.ouvrir_session(request, utilisateur, methode_mfa=methode)
        return Response(
            {"utilisateur": donnees_moi(utilisateur), "codes_secours_restants": restants}
        )


class VueDeconnexion(VueAuth):
    permission_classes = [EstAuthentifie]

    @extend_schema(
        operation_id="auth_deconnexion",
        summary="Déconnexion (révoque la session de cet appareil)",
        description="Révoque la session de cet appareil et vide la session.",
        request=None,
        responses={
            204: OpenApiResponse(description="Déconnecté."),
            401: ERREUR_401,
            403: ERREUR_403_CSRF,
        },
        tags=["auth"],
    )
    def post(self, request):
        connexion.fermer_session(request, MotifFinSession.DECONNEXION)
        return Response(status=status.HTTP_204_NO_CONTENT)
