"""Services de la connexion (architecture § 4.2, § 4.6, § 4.8, décisions P2, P3, P6).

- ``ReglesSecurite`` : durées et seuils de l'établissement (``ParametresEtablissement``)
  ou, pour un super-administrateur FYXOP, les valeurs fixes de la plateforme
  (inactivité 10 min, session 8 h, § 3.8) ;
- ``est_bloque`` / ``enregistrer_echec`` : verrouillage après N échecs (mot de passe
  et MFA confondus), puis déblocage administrateur au k-ième verrouillage en 24 h ;
- ``ouvrir_session`` : fin de la connexion (anti-fixation, ``login()``, contexte de
  session, ``session_appareil``, remise à zéro, ``derniere_connexion``, audit,
  connexion inhabituelle) ; réutilisée par l'activation et le réenrôlement (B6) ;
- ``fermer_session`` : déconnexion.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from django.contrib.auth import login, logout
from django.utils import timezone

from alpha.audit.models import Categorie
from alpha.audit.services import ACTEUR_ANONYME, journaliser
from alpha.core import contexte
from alpha.tenancy.models import ParametresEtablissement

from . import alertes, sessions
from .models import MotifFinSession, Utilisateur

# Clés de la session Django.
CLE_PREAUTH = "preauth"
CLE_TENANT = "tenant_id"
CLE_SCOPE = "scope"
CLE_MFA_LE = "mfa_le"
CLE_SESSION_APPAREIL = "session_appareil_id"

DUREE_PREAUTH = datetime.timedelta(minutes=5)
BACKEND = "django.contrib.auth.backends.ModelBackend"

# Motifs d'échec (champ ``apres.motif`` de ``auth.connexion.echec``).
MOTIF_EMAIL_INCONNU = "EMAIL_INCONNU"
MOTIF_MOT_DE_PASSE = "MOT_DE_PASSE"
MOTIF_MFA = "MFA"
MOTIF_VERROUILLE = "COMPTE_VERROUILLE"
MOTIF_INACTIF = "COMPTE_INACTIF"
MOTIF_SUSPENDU = "ETABLISSEMENT_SUSPENDU"


@dataclass(frozen=True)
class ReglesSecurite:
    inactivite: datetime.timedelta
    duree_max: datetime.timedelta
    tentatives_max: int
    verrouillage: datetime.timedelta
    verrouillages_max_24h: int
    mdp_expiration_jours: int | None

    @classmethod
    def plateforme(cls) -> ReglesSecurite:
        """Super-administrateur FYXOP (§ 3.8) : non paramétrable."""
        return cls(
            inactivite=datetime.timedelta(minutes=10),
            duree_max=datetime.timedelta(hours=8),
            tentatives_max=5,
            verrouillage=datetime.timedelta(minutes=15),
            verrouillages_max_24h=3,
            mdp_expiration_jours=None,
        )

    @classmethod
    def de_parametres(cls, p: ParametresEtablissement) -> ReglesSecurite:
        return cls(
            inactivite=datetime.timedelta(minutes=p.inactivite_session_min),
            duree_max=datetime.timedelta(hours=p.duree_max_session_h),
            tentatives_max=p.tentatives_max,
            verrouillage=datetime.timedelta(minutes=p.verrouillage_min),
            verrouillages_max_24h=p.verrouillages_max_24h,
            mdp_expiration_jours=p.mdp_expiration_jours,
        )


def regles_pour(utilisateur: Utilisateur) -> ReglesSecurite:
    """Règles applicables (lecture sous le contexte courant de l'utilisateur)."""
    if utilisateur.est_super_admin:
        return ReglesSecurite.plateforme()
    parametres = ParametresEtablissement.objects.filter(
        etablissement_id=utilisateur.etablissement_id
    ).first()
    if parametres is None:  # établissement mal provisionné : valeurs par défaut validées (P2)
        parametres = ParametresEtablissement(etablissement_id=utilisateur.etablissement_id)
    return ReglesSecurite.de_parametres(parametres)


def regles_courantes() -> ReglesSecurite:
    """Règles du contexte courant (portée « platform » ou établissement courant)."""
    tenant = contexte.tenant_courant()
    if tenant is None:
        return ReglesSecurite.plateforme()
    parametres = ParametresEtablissement.objects.filter(etablissement_id=tenant).first()
    return ReglesSecurite.de_parametres(
        parametres or ParametresEtablissement(etablissement_id=tenant)
    )


def mot_de_passe_expire(utilisateur: Utilisateur, regles: ReglesSecurite) -> bool:
    """Expiration périodique (P3) : désactivée tant que ``mdp_expiration_jours`` est vide."""
    if not regles.mdp_expiration_jours:
        return False
    reference = utilisateur.mdp_modifie_le or utilisateur.active_le or utilisateur.cree_le
    if reference is None:
        return False
    return timezone.now() - reference > datetime.timedelta(days=regles.mdp_expiration_jours)


# --- Verrouillage -----------------------------------------------------------------------


def masquer_email(email: str) -> str:
    """« m.sow@etablissement.sn » → « m.sow@… » (objet des événements d'échec)."""
    local, _, _ = str(email or "").partition("@")
    return f"{local[:60]}@…"


def est_bloque(utilisateur: Utilisateur) -> bool:
    if utilisateur.bloque_par_admin:
        return True
    return utilisateur.verrouille_jusqua is not None and utilisateur.verrouille_jusqua > (
        timezone.now()
    )


def tentatives_restantes(utilisateur: Utilisateur, regles: ReglesSecurite) -> int:
    return max(regles.tentatives_max - utilisateur.echecs_connexion, 0)


def enregistrer_echec(utilisateur: Utilisateur, regles: ReglesSecurite) -> bool:
    """Compte un échec (mot de passe ou MFA) ; renvoie vrai si le compte vient d'être verrouillé.

    Au ``tentatives_max``-ième échec : verrouillage pour ``verrouillage_min``,
    ``verrouillages_24h += 1`` (le compteur repart de zéro si le verrouillage
    précédent a pris fin il y a plus de 24 h) ; au ``verrouillages_max_24h``-ième :
    ``bloque_par_admin``. L'appelant journalise et prévient l'utilisateur.
    """
    maintenant = timezone.now()
    utilisateur.echecs_connexion += 1
    verrouille = False
    if utilisateur.echecs_connexion >= regles.tentatives_max:
        precedent = utilisateur.verrouille_jusqua
        if precedent is None or precedent < maintenant - datetime.timedelta(hours=24):
            utilisateur.verrouillages_24h = 0
        utilisateur.verrouillages_24h += 1
        utilisateur.verrouille_jusqua = maintenant + regles.verrouillage
        utilisateur.echecs_connexion = 0
        if utilisateur.verrouillages_24h >= regles.verrouillages_max_24h:
            utilisateur.bloque_par_admin = True
        verrouille = True
    utilisateur.save(
        update_fields=[
            "echecs_connexion",
            "verrouille_jusqua",
            "verrouillages_24h",
            "bloque_par_admin",
            "modifie_le",
        ]
    )
    return verrouille


# --- Audit -------------------------------------------------------------------------------


def journaliser_echec(
    motif: str,
    *,
    email: str,
    utilisateur: Utilisateur | None = None,
    detail: str = "",
    plateforme: bool = False,
) -> None:
    """``auth.connexion.echec`` écrit HORS transaction (survit à toute annulation, § 3.3).

    Acteur ANONYME (pas encore authentifié) ; objet = l'utilisateur visé s'il est
    connu, libellé = e-mail masqué. Jamais de mot de passe ni de code.
    ``plateforme`` : chaîne de la plateforme (e-mail inconnu, § 4.2 étape 3).
    """
    from alpha.audit.services import COURANT

    journaliser(
        "auth.connexion.echec",
        Categorie.CONNEXION,
        objet=("comptes.utilisateur", utilisateur.pk) if utilisateur else None,
        objet_libelle=masquer_email(email),
        apres={"motif": motif},
        detail=detail or f"Échec de connexion · {motif}",
        acteur=ACTEUR_ANONYME,
        etablissement_id=None if plateforme else COURANT,
        hors_transaction=True,
    )


def journaliser_verrouillage(utilisateur: Utilisateur) -> None:
    journaliser(
        "auth.verrouillage",
        Categorie.SECURITE,
        objet=("comptes.utilisateur", utilisateur.pk),
        objet_libelle=utilisateur.nom_complet,
        apres={
            "verrouille_jusqua": utilisateur.verrouille_jusqua,
            "verrouillages_24h": utilisateur.verrouillages_24h,
            "bloque_par_admin": utilisateur.bloque_par_admin,
        },
        detail=(
            "Compte bloqué : déblocage par un administrateur"
            if utilisateur.bloque_par_admin
            else "Compte verrouillé temporairement"
        ),
        acteur=ACTEUR_ANONYME,
        hors_transaction=True,
    )


# --- Ouverture et fermeture de session -------------------------------------------------------


def ouvrir_session(request, utilisateur: Utilisateur, *, methode_mfa: str, detail: str = ""):
    """Ouvre la session après MFA (§ 4.2, étapes 11 et 12). Renvoie la ``SessionAppareil``.

    À appeler sous le contexte de l'utilisateur (``contexte_tenant``) ; les
    écritures (session, audit) suivent la transaction de la requête.
    """
    maintenant = timezone.now()
    regles = regles_pour(utilisateur)
    request.session.pop(CLE_PREAUTH, None)
    # Anti-fixation : nouvelle clé de session, puis login() (qui tourne aussi le jeton CSRF).
    request.session.cycle_key()
    login(request, utilisateur, backend=BACKEND)
    if utilisateur.est_super_admin:
        request.session.pop(CLE_TENANT, None)
        request.session[CLE_SCOPE] = contexte.SCOPE_PLATFORM
    else:
        request.session[CLE_TENANT] = str(utilisateur.etablissement_id)
        request.session[CLE_SCOPE] = contexte.SCOPE_TENANT
    request.session[CLE_MFA_LE] = maintenant.isoformat()
    if request.session.session_key is None:
        request.session.save()

    agent = request.headers.get("User-Agent", "")
    ip = contexte.ip()
    inhabituelle = sessions.connexion_inhabituelle(utilisateur, agent, ip)
    appareil = sessions.creer_session_appareil(
        utilisateur,
        request.session.session_key,
        methode_mfa=methode_mfa,
        duree_max=regles.duree_max,
        user_agent=agent,
        ip=ip,
    )
    request.session[CLE_SESSION_APPAREIL] = str(appareil.id)

    utilisateur.echecs_connexion = 0
    utilisateur.derniere_connexion = maintenant
    utilisateur.save(update_fields=["echecs_connexion", "derniere_connexion", "modifie_le"])

    journaliser(
        "auth.connexion.succes",
        Categorie.CONNEXION,
        objet=appareil,
        objet_libelle=appareil.appareil,
        apres={"methode_mfa": methode_mfa, "session_id": appareil.id},
        detail=detail or "Connexion réussie · double authentification OK",
        acteur=utilisateur,
    )
    if inhabituelle:
        journaliser(
            "securite.connexion_inhabituelle",
            Categorie.SECURITE,
            objet=appareil,
            objet_libelle=appareil.appareil,
            apres={"appareil": appareil.appareil, "ip": ip},
            detail="Connexion depuis un appareil ou un lieu inhabituel : e-mail envoyé",
            acteur=utilisateur,
        )
        alertes.nouvelle_connexion(utilisateur, appareil.appareil, ip)
    return appareil


def fermer_session(
    request, motif: str = MotifFinSession.DECONNEXION, *, hors_transaction: bool = False
) -> None:
    """Déconnexion (§ 4.6) : révocation de la session d'appareil, audit, ``logout()``.

    ``hors_transaction=True`` : l'événement est écrit par la connexion indépendante.
    Obligatoire quand la même requête peut ensuite journaliser un échec hors
    transaction dans la même chaîne (sinon la transaction de la requête détiendrait
    déjà le verrou de la chaîne d'audit).
    """
    utilisateur = request.user
    cle = request.session.session_key
    appareil = sessions.session_par_cle(cle) if cle else None
    if appareil is not None:
        sessions.revoquer_session(appareil, motif)
    if getattr(utilisateur, "is_authenticated", False):
        journaliser(
            "auth.deconnexion",
            Categorie.CONNEXION,
            objet=appareil if appareil is not None else None,
            objet_libelle=appareil.appareil if appareil is not None else "",
            apres={"motif": motif},
            detail="Déconnexion",
            acteur=utilisateur,
            hors_transaction=hors_transaction,
        )
    logout(request)


def nouvel_etat_preauth(utilisateur: Utilisateur) -> dict:
    return {
        "user_id": str(utilisateur.pk),
        "tenant_id": str(utilisateur.etablissement_id) if utilisateur.etablissement_id else None,
        "scope": contexte.SCOPE_PLATFORM if utilisateur.est_super_admin else contexte.SCOPE_TENANT,
        "expire": (timezone.now() + DUREE_PREAUTH).isoformat(),
        "essais_mfa": 0,
    }


def lire_preauth(request) -> dict | None:
    """État pré-authentifié valide de la session, ou None (absent, incohérent ou expiré)."""
    etat = request.session.get(CLE_PREAUTH)
    if not isinstance(etat, dict):
        return None
    try:
        uuid.UUID(etat["user_id"])
        expire = datetime.datetime.fromisoformat(etat["expire"])
    except (KeyError, TypeError, ValueError):
        return None
    if expire <= timezone.now():
        return None
    return etat
