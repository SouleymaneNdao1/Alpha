"""Double authentification : TOTP, codes de secours, step-up (architecture § 4.2 à § 4.5, § 4.9).

- ``verifier_totp(utilisateur, code)`` : code à 6 chiffres de l'Authenticator
  ``ACTIF``, fenêtre ±1 pas ; le compteur accepté doit être strictement
  supérieur à ``dernier_pas`` (anti-rejeu), puis devient le nouveau ``dernier_pas``.
  Un Authenticator ``SUSPENDU`` (téléphone perdu) est refusé.
- ``consommer_code_secours(utilisateur, saisi)`` : code de secours à usage unique,
  recherché par HMAC parmi les codes ni utilisés ni invalidés, sous ``FOR UPDATE``.
- ``creer_authenticator_en_attente`` / ``confirmer_authenticator`` /
  ``generer_codes_secours`` : enrôlement (utilisés par l'activation, B6).
- ``verifier_signature_autorisee`` : refus de signer après « téléphone perdu ».

Aucune fonction ne journalise un secret, un code ou un HMAC.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid

import pyotp
from django.conf import settings
from django.utils import timezone
from rest_framework import status

from alpha.core.erreurs import ErreurApi

from . import chiffrement
from .models import AuthenticatorTOTP, CodeSecours, StatutAuthenticator, Utilisateur

# Alphabet Crockford base32 (sans I, L, O, U) : 8 caractères = 40 bits (§ 2.2).
ALPHABET_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
NB_CODES_PAR_LOT = 10
LONGUEUR_CODE_SECOURS = 8
# Confusions courantes à la saisie (règles de décodage Crockford).
_CORRECTIONS = str.maketrans({"O": "0", "I": "1", "L": "1"})
_CODE_TOTP = re.compile(r"^\d{6}$")

SIGNATURE_BLOQUEE = "SIGNATURE_BLOQUEE"


# --- TOTP ------------------------------------------------------------------------------------


def nouveau_secret() -> str:
    """Secret base32 de 160 bits (32 caractères)."""
    return pyotp.random_base32(length=32)


def _totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, digits=6, interval=30)


def authenticator_actif(utilisateur: Utilisateur, *, verrouiller: bool = False):
    qs = AuthenticatorTOTP.objects.filter(
        utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.ACTIF
    )
    if verrouiller:
        qs = qs.select_for_update()
    return qs.first()


def pas_accepte(secret: str, code: str, dernier_pas: int | None) -> int | None:
    """Compteur TOTP correspondant au code (fenêtre ±1), ou None (code faux ou rejoué)."""
    if not _CODE_TOTP.match(code or ""):
        return None
    totp = _totp(secret)
    courant = totp.timecode(timezone.now())
    accepte = None
    for compteur in (courant - 1, courant, courant + 1):
        if hmac.compare_digest(totp.generate_otp(compteur), code):
            accepte = compteur
    if accepte is None or (dernier_pas is not None and accepte <= dernier_pas):
        return None
    return accepte


def verifier_totp(utilisateur: Utilisateur, code: str) -> bool:
    """Vérifie un code de l'Authenticator ACTIF et consomme son pas (anti-rejeu)."""
    authenticator = authenticator_actif(utilisateur, verrouiller=True)
    if authenticator is None:
        return False
    secret = chiffrement.dechiffrer(authenticator.secret_chiffre)
    compteur = pas_accepte(secret, str(code or "").strip(), authenticator.dernier_pas)
    if compteur is None:
        return False
    authenticator.dernier_pas = compteur
    authenticator.save(update_fields=["dernier_pas"])
    return True


def creer_authenticator_en_attente(
    utilisateur: Utilisateur, libelle: str = ""
) -> tuple[AuthenticatorTOTP, str]:
    """Nouvel Authenticator EN_ATTENTE (les précédents en attente sont révoqués).

    Renvoie (ligne, secret en clair) : le secret ne sert qu'à construire le QR
    code et l'affichage, il n'est ni stocké en clair ni journalisé.
    """
    maintenant = timezone.now()
    AuthenticatorTOTP.objects.filter(
        utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.EN_ATTENTE
    ).update(statut=StatutAuthenticator.REVOQUE, revoque_le=maintenant)
    secret = nouveau_secret()
    authenticator = AuthenticatorTOTP.objects.create(
        utilisateur=utilisateur,
        etablissement_id=utilisateur.etablissement_id,
        secret_chiffre=chiffrement.chiffrer(secret),
        cle_version=chiffrement.version_courante(),
        libelle=libelle[:80],
        statut=StatutAuthenticator.EN_ATTENTE,
    )
    return authenticator, secret


def confirmer_authenticator(authenticator: AuthenticatorTOTP, code: str) -> bool:
    """Confirme un Authenticator EN_ATTENTE par un premier code ; l'actif précédent est révoqué."""
    if authenticator.statut != StatutAuthenticator.EN_ATTENTE:
        return False
    secret = chiffrement.dechiffrer(authenticator.secret_chiffre)
    compteur = pas_accepte(secret, str(code or "").strip(), authenticator.dernier_pas)
    if compteur is None:
        return False
    maintenant = timezone.now()
    AuthenticatorTOTP.objects.filter(
        utilisateur_id=authenticator.utilisateur_id,
        statut__in=[StatutAuthenticator.ACTIF, StatutAuthenticator.SUSPENDU],
    ).update(statut=StatutAuthenticator.REVOQUE, revoque_le=maintenant)
    authenticator.statut = StatutAuthenticator.ACTIF
    authenticator.dernier_pas = compteur
    authenticator.confirme_le = maintenant
    authenticator.save(update_fields=["statut", "dernier_pas", "confirme_le"])
    return True


# --- Codes de secours -----------------------------------------------------------------------


def normaliser_code_secours(saisi: str) -> str:
    """Majuscules, sans tiret ni espace, confusions O/I/L corrigées."""
    texte = re.sub(r"[\s-]", "", str(saisi or "")).upper()
    return texte.translate(_CORRECTIONS)


def hmac_code_secours(normalise: str) -> str:
    poivre = settings.ALPHA_HMAC_POIVRE.encode("utf-8")
    return hmac.new(poivre, normalise.encode("utf-8"), hashlib.sha256).hexdigest()


def _code_aleatoire() -> str:
    brut = "".join(secrets.choice(ALPHABET_CROCKFORD) for _ in range(LONGUEUR_CODE_SECOURS))
    return f"{brut[:4]}-{brut[4:]}"


def generer_codes_secours(utilisateur: Utilisateur) -> list[str]:
    """Nouveau lot de 10 codes ``XXXX-XXXX`` ; les lots précédents sont invalidés.

    Les codes en clair ne sont renvoyés qu'une fois (affichage) ; seuls leurs HMAC
    sont enregistrés.
    """
    maintenant = timezone.now()
    CodeSecours.objects.filter(
        utilisateur_id=utilisateur.pk, utilise_le__isnull=True, invalide_le__isnull=True
    ).update(invalide_le=maintenant)
    lot = uuid.uuid4()
    codes: list[str] = []
    empreintes: set[str] = set(
        CodeSecours.objects.filter(utilisateur_id=utilisateur.pk).values_list(
            "code_hmac", flat=True
        )
    )
    while len(codes) < NB_CODES_PAR_LOT:
        code = _code_aleatoire()
        empreinte = hmac_code_secours(normaliser_code_secours(code))
        if empreinte in empreintes:
            continue
        empreintes.add(empreinte)
        codes.append(code)
        CodeSecours.objects.create(
            utilisateur=utilisateur,
            etablissement_id=utilisateur.etablissement_id,
            lot=lot,
            code_hmac=empreinte,
        )
    return codes


def codes_secours_restants(utilisateur: Utilisateur) -> int:
    return CodeSecours.objects.filter(
        utilisateur_id=utilisateur.pk, utilise_le__isnull=True, invalide_le__isnull=True
    ).count()


def consommer_code_secours(utilisateur: Utilisateur, saisi: str) -> bool:
    """Consomme un code de secours valide (usage unique) ; faux si inconnu ou déjà utilisé."""
    normalise = normaliser_code_secours(saisi)
    if len(normalise) != LONGUEUR_CODE_SECOURS or any(
        c not in ALPHABET_CROCKFORD for c in normalise
    ):
        return False
    code = (
        CodeSecours.objects.select_for_update()
        .filter(
            utilisateur_id=utilisateur.pk,
            code_hmac=hmac_code_secours(normalise),
            utilise_le__isnull=True,
            invalide_le__isnull=True,
        )
        .first()
    )
    if code is None:
        return False
    code.utilise_le = timezone.now()
    code.save(update_fields=["utilise_le"])
    return True


# --- Signature (S2) ----------------------------------------------------------------------------


def verifier_signature_autorisee(utilisateur: Utilisateur) -> None:
    """Lève 403 ``SIGNATURE_BLOQUEE`` si l'utilisateur ne peut pas signer (téléphone perdu).

    À appeler par toute signature de décision (S2), en plus du step-up TOTP.
    """
    if not utilisateur.peut_signer:
        raise ErreurApi(
            SIGNATURE_BLOQUEE,
            "La signature est bloquée sur votre compte suite au signalement de votre "
            "téléphone. Contactez votre administrateur.",
            statut=status.HTTP_403_FORBIDDEN,
        )
