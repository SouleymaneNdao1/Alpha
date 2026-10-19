"""Services de la console FYXOP (architecture § 3.8, § 5.7, décisions P4 et P6 ; tâche B10).

Seules opérations de la plateforme qui écrivent dans un établissement, toutes sous
``contexte_tenant(cible)`` :

- ``provisionner_etablissement`` : établissement, paramètres, rôles par défaut, unité
  racine, invitation du premier administrateur ;
- ``inviter_administrateur`` : invitation sur le rôle « Administrateur ALPHA » ;
- ``modifier_etablissement`` : raison sociale et, si le réglage
  ``ALPHA_PLATEFORME_SUSPENSION_MANUELLE`` est activé (P6, désactivé par défaut),
  changement de statut (suspension, lecture seule, réactivation) ;
- ``reinitialiser_authenticator`` : décision P4, via ``telephone.reinitialiser_par_fyxop``.

Chacune est journalisée DEUX FOIS (``journaliser_double``) : dans la chaîne de la plateforme
et dans celle de l'établissement (acteur ``SUPER_ADMIN``, catégorie ``SUPER_ADMIN``).

Le super-administrateur ne lit jamais le contenu d'un établissement : la console ne voit
que la table ``etablissement`` et les compteurs de ``alpha_stats_etablissements()``
(``statistiques``). Les erreurs sont des ``ErreurApi`` que les vues RETOURNENT.

``creer_super_admin`` et ``nouveau_lien_super_admin`` servent la commande
``manage.py creer_super_admin`` (portée « platform », chaîne d'audit de la plateforme).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework import status

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie, TypeActeur
from alpha.audit.services import Acteur, journaliser
from alpha.comptes import administration, emails, jetons, sessions, telephone
from alpha.comptes.models import (
    HistoriqueMotDePasse,
    MotifFinSession,
    SessionAppareil,
    StatutUtilisateur,
    Utilisateur,
)
from alpha.comptes.resolution import resoudre_connexion
from alpha.core import contexte
from alpha.core.erreurs import INTROUVABLE, PERMISSION_REFUSEE, VALIDATION, ErreurApi
from alpha.organisation.models import Role, TypeUnite
from alpha.organisation.roles_defaut import (
    CODE_ADMINISTRATEUR,
    catalogue_par_defaut,
    semer_roles_par_defaut,
)
from alpha.organisation.services import creer_unite, titulaires_administration
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement, ParametresEtablissement, StatutEtablissement

from .sql import COLONNES_STATS

CODE_EXISTE = "CODE_EXISTE"
EMAIL_EXISTE = administration.EMAIL_EXISTE
SUSPENSION_DESACTIVEE = "SUSPENSION_MANUELLE_DESACTIVEE"
STATUT_INVALIDE = "STATUT_INVALIDE"
ETABLISSEMENT_ARCHIVE = "ETABLISSEMENT_ARCHIVE"
ROLE_ADMINISTRATEUR_ABSENT = "ROLE_ADMINISTRATEUR_ABSENT"
PAS_ADMINISTRATEUR = "PAS_ADMINISTRATEUR"

#: Unité racine semée au provisionnement (remarque de B3).
CODE_UNITE_RACINE = "direction-generale"
LIBELLE_UNITE_RACINE = "Direction générale"

#: Statuts qu'un super-administrateur peut poser à la main (P6). ``ARCHIVE`` relève d'une
#: procédure d'exploitation documentée, pas de la console.
STATUTS_MANUELS = (
    StatutEtablissement.ACTIF,
    StatutEtablissement.LECTURE_SEULE,
    StatutEtablissement.SUSPENDU,
)

ACTEUR_COMMANDE = Acteur(TypeActeur.SYSTEME, None, "Commande creer_super_admin")


def suspension_manuelle_active() -> bool:
    """Réglage P6 : suspension manuelle d'un établissement par le super-admin (défaut : non)."""
    return bool(getattr(settings, "ALPHA_PLATEFORME_SUSPENSION_MANUELLE", False))


# --- Outils -----------------------------------------------------------------------------------


def _exiger_plateforme(par: Utilisateur) -> None:
    """Défense en profondeur : super-admin, en portée « platform », sans établissement courant."""
    if not (
        getattr(par, "est_super_admin", False)
        and contexte.scope_courant() == contexte.SCOPE_PLATFORM
        and contexte.tenant_courant() is None
    ):
        raise ErreurApi(
            PERMISSION_REFUSEE,
            "Opération réservée au super-administrateur FYXOP.",
            statut=status.HTTP_403_FORBIDDEN,
        )


def _introuvable() -> ErreurApi:
    return ErreurApi(INTROUVABLE, "Établissement introuvable.", statut=status.HTTP_404_NOT_FOUND)


def etablissement_ou_404(etablissement_id: Any, *, verrou: bool = False) -> Etablissement:
    """Établissement lu en portée « platform » (la RLS l'autorise), sinon 404."""
    qs = Etablissement.objects.all()
    if verrou:
        qs = qs.select_for_update()
    etablissement = qs.filter(pk=etablissement_id).first()
    if etablissement is None:
        raise _introuvable()
    return etablissement


def _libelle(etablissement: Etablissement) -> str:
    return f"{etablissement.raison_sociale} ({etablissement.code})"


@dataclass(frozen=True)
class DoubleTrace:
    """Les deux événements d'une action de plateforme (chaîne plateforme, chaîne établissement)."""

    plateforme: Any
    etablissement: Any


def journaliser_double(
    action: str,
    *,
    etablissement: Etablissement,
    par: Utilisateur,
    objet: Any = None,
    objet_libelle: str | None = None,
    avant: Any = None,
    apres: Any = None,
    detail: str = "",
) -> DoubleTrace:
    """Écrit l'action dans la chaîne de la plateforme PUIS dans celle de l'établissement (§ 3.8).

    Même action, même acteur (``SUPER_ADMIN``), catégorie ``SUPER_ADMIN`` ; l'événement de la
    plateforme porte en plus le code de l'établissement. Appelée en portée « platform », dans
    la transaction de l'action (les deux traces sont validées ou annulées avec elle).
    """
    objet = objet if objet is not None else ("tenancy.etablissement", etablissement.id)
    libelle = objet_libelle if objet_libelle is not None else _libelle(etablissement)
    apres_plateforme = {
        **(apres or {}),
        "etablissement_id": str(etablissement.id),
        "etablissement_code": etablissement.code,
    }
    trace_plateforme = journaliser(
        action,
        Categorie.SUPER_ADMIN,
        objet=objet,
        objet_libelle=libelle,
        avant=avant,
        apres=apres_plateforme,
        detail=detail,
        acteur=par,
        etablissement_id=None,
    )
    with contexte_tenant(etablissement.id, utilisateur_id=par.pk):
        trace_etablissement = journaliser(
            action,
            Categorie.SUPER_ADMIN,
            objet=objet,
            objet_libelle=libelle,
            avant=avant,
            apres=apres,
            detail=detail,
            acteur=par,
        )
    return DoubleTrace(trace_plateforme, trace_etablissement)


# --- Statistiques (sans contenu) ------------------------------------------------------------


def statistiques(etablissement_id: Any = None) -> dict[uuid.UUID, dict[str, Any]]:
    """Compteurs par établissement, via ``alpha_stats_etablissements`` (portée « platform »)."""
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT * FROM alpha_stats_etablissements(%s::uuid)",
            [str(etablissement_id) if etablissement_id else None],
        )
        colonnes = [c.name for c in curseur.description]
        if tuple(colonnes) != COLONNES_STATS:  # garde-fou : jamais de colonne inattendue
            raise RuntimeError(f"Colonnes inattendues dans alpha_stats_etablissements : {colonnes}")
        return {
            ligne[0]: dict(zip(colonnes[1:], ligne[1:], strict=True))
            for ligne in curseur.fetchall()
        }


# --- Provisionnement --------------------------------------------------------------------------


def verifier_disponibilite(*, code: str | None = None, email: str | None = None) -> None:
    """409 ``CODE_EXISTE`` / ``EMAIL_EXISTE`` (e-mail unique sur la plateforme, P1)."""
    if code is not None and Etablissement.objects.filter(code=code).exists():
        raise ErreurApi(
            CODE_EXISTE,
            "Un établissement porte déjà ce code.",
            statut=status.HTTP_409_CONFLICT,
            details={"code": ["Code déjà utilisé."]},
        )
    if email is not None and resoudre_connexion(email.strip()) is not None:
        raise ErreurApi(
            EMAIL_EXISTE,
            "Cette adresse e-mail est déjà utilisée par un compte ALPHA.",
            statut=status.HTTP_409_CONFLICT,
            details={"administrateur": {"email": ["Adresse déjà utilisée."]}},
        )


def provisionner_etablissement(
    *,
    par: Utilisateur,
    code: str,
    raison_sociale: str,
    type: str,
    pays: str,
    administrateur: dict[str, str],
) -> tuple[Etablissement, Utilisateur]:
    """Crée un établissement prêt à l'emploi et invite son premier administrateur (§ 3.8).

    Dans une seule transaction : établissement (portée « platform ») ; sous son contexte,
    paramètres par défaut (P2, P3), catalogue de rôles par défaut, unité racine
    « Direction générale » ; invitation de l'administrateur sur le rôle « Administrateur
    ALPHA » rattaché à l'unité racine (préférences de notification, jeton, e-mail après le
    commit). Double journalisation : ``plateforme.etablissement.cree`` et
    ``plateforme.administrateur.invite`` (plus ``unite.creee`` et ``utilisateur.invite``
    dans la chaîne de l'établissement).
    """
    _exiger_plateforme(par)
    verifier_disponibilite(code=code, email=administrateur["email"])
    with transaction.atomic():
        try:
            with transaction.atomic():
                etablissement = Etablissement.objects.create(
                    code=code,
                    raison_sociale=raison_sociale.strip(),
                    type=type,
                    pays=pays,
                    cree_par=par,
                )
        except IntegrityError:  # course entre deux provisionnements du même code
            raise ErreurApi(
                CODE_EXISTE, "Un établissement porte déjà ce code.", statut=409
            ) from None
        nb_roles = len(catalogue_par_defaut(type))
        journaliser_double(
            "plateforme.etablissement.cree",
            etablissement=etablissement,
            par=par,
            apres={
                "code": etablissement.code,
                "raison_sociale": etablissement.raison_sociale,
                "type": etablissement.type,
                "pays": etablissement.pays,
                "statut": etablissement.statut,
                "nb_roles_par_defaut": nb_roles,
                "unite_racine": CODE_UNITE_RACINE,
            },
            detail="Provisionnement de l'établissement par FYXOP",
        )
        with contexte_tenant(etablissement.id, utilisateur_id=par.pk):
            ParametresEtablissement.objects.create(etablissement=etablissement)
            semer_roles_par_defaut(etablissement)
            racine = creer_unite(
                par=par,
                type=TypeUnite.DIRECTION,
                code=CODE_UNITE_RACINE,
                libelle=LIBELLE_UNITE_RACINE,
            )
        admin = _inviter(etablissement, par=par, unite=racine, **administrateur)
    return etablissement, admin


def _inviter(
    etablissement: Etablissement,
    *,
    par: Utilisateur,
    email: str,
    prenom: str,
    nom: str,
    unite=None,
) -> Utilisateur:
    """Invitation sur le rôle système « Administrateur ALPHA » + double journalisation."""
    with contexte_tenant(etablissement.id, utilisateur_id=par.pk):
        role = Role.objects.filter(code=CODE_ADMINISTRATEUR, actif=True).first()
        if role is None:
            raise ErreurApi(
                ROLE_ADMINISTRATEUR_ABSENT,
                "Le rôle « Administrateur ALPHA » est absent du catalogue de l'établissement.",
                statut=status.HTTP_409_CONFLICT,
            )
        utilisateur = administration.inviter(
            par=par, email=email, prenom=prenom, nom=nom, role_id=role.id, unite=unite
        )
    journaliser_double(
        "plateforme.administrateur.invite",
        etablissement=etablissement,
        par=par,
        objet=("comptes.utilisateur", utilisateur.id),
        objet_libelle=utilisateur.email,
        apres={
            "email": utilisateur.email,
            "prenom": utilisateur.prenom,
            "nom": utilisateur.nom,
            "role": role.libelle,
        },
        detail=f"Invitation d'un administrateur de l'établissement « {role.libelle} »",
    )
    return utilisateur


def inviter_administrateur(
    etablissement_id: Any, *, par: Utilisateur, email: str, prenom: str, nom: str
) -> Utilisateur:
    """Invite un administrateur supplémentaire (ex. remplacement du dernier administrateur)."""
    _exiger_plateforme(par)
    etablissement = etablissement_ou_404(etablissement_id)
    if etablissement.statut == StatutEtablissement.ARCHIVE:
        raise _archive()
    verifier_disponibilite(email=email)
    with transaction.atomic():
        return _inviter(etablissement, par=par, email=email, prenom=prenom, nom=nom)


def _archive() -> ErreurApi:
    return ErreurApi(
        ETABLISSEMENT_ARCHIVE,
        "Cet établissement est archivé : aucune modification n'est possible depuis la console.",
        statut=status.HTTP_409_CONFLICT,
    )


# --- Modification et statut (P6) ----------------------------------------------------------------


def controler_modification(
    etablissement: Etablissement, *, statut: str | None = None, motif: str = ""
) -> None:
    """Contrôles préalables (appelés AVANT le step-up par la vue, puis par le service)."""
    if etablissement.statut == StatutEtablissement.ARCHIVE:
        raise _archive()
    if statut is None or statut == etablissement.statut:
        return
    if not suspension_manuelle_active():
        raise ErreurApi(
            SUSPENSION_DESACTIVEE,
            "La suspension manuelle d'un établissement n'est pas activée sur cette plateforme.",
            statut=status.HTTP_403_FORBIDDEN,
        )
    if statut not in STATUTS_MANUELS:
        raise ErreurApi(
            STATUT_INVALIDE,
            "Statut non modifiable depuis la console.",
            details={"statut": [f"Valeurs permises : {', '.join(STATUTS_MANUELS)}."]},
        )
    if not (motif or "").strip():
        raise ErreurApi(
            VALIDATION,
            "Certaines données sont invalides.",
            details={"motif": ["Le motif est obligatoire pour changer le statut."]},
        )


def modifier_etablissement(
    etablissement_id: Any,
    *,
    par: Utilisateur,
    raison_sociale: str | None = None,
    statut: str | None = None,
    motif: str = "",
) -> Etablissement:
    """Raison sociale (``plateforme.etablissement.modifie``) et statut (``…statut``, P6).

    Suspension : toutes les sessions ouvertes de l'établissement sont révoquées (en plus du
    refus 403 ``ETABLISSEMENT_SUSPENDU`` posé par ``StatutEtablissementMiddleware``).
    """
    _exiger_plateforme(par)
    with transaction.atomic():
        etablissement = etablissement_ou_404(etablissement_id, verrou=True)
        controler_modification(etablissement, statut=statut, motif=motif)
        raison_sociale = raison_sociale.strip() if raison_sociale is not None else None
        if raison_sociale is not None and raison_sociale != etablissement.raison_sociale:
            ancienne = etablissement.raison_sociale
            etablissement.raison_sociale = raison_sociale
            etablissement.save(update_fields=["raison_sociale", "modifie_le"])
            journaliser_double(
                "plateforme.etablissement.modifie",
                etablissement=etablissement,
                par=par,
                avant={"raison_sociale": ancienne},
                apres={"raison_sociale": raison_sociale},
                detail="Raison sociale modifiée par FYXOP",
            )
        if statut is not None and statut != etablissement.statut:
            ancien = etablissement.statut
            etablissement.statut = statut
            etablissement.save(update_fields=["statut", "modifie_le"])
            revoquees = 0
            if statut == StatutEtablissement.SUSPENDU:
                revoquees = _revoquer_sessions_etablissement(etablissement, par)
            journaliser_double(
                "plateforme.etablissement.statut",
                etablissement=etablissement,
                par=par,
                avant={"statut": ancien},
                apres={
                    "statut": statut,
                    "motif": motif.strip()[:500],
                    "sessions_revoquees": revoquees,
                },
                detail=f"Statut : {StatutEtablissement(ancien).label} → "
                f"{StatutEtablissement(statut).label}",
            )
    return etablissement


def _revoquer_sessions_etablissement(etablissement: Etablissement, par: Utilisateur) -> int:
    with contexte_tenant(etablissement.id, utilisateur_id=par.pk):
        nombre = 0
        for session in SessionAppareil.objects.filter(revoque_le__isnull=True).select_for_update():
            nombre += int(sessions.revoquer_session(session, MotifFinSession.REVOCATION_ADMIN))
        return nombre


# --- Décision P4 ------------------------------------------------------------------------------


def reinitialiser_authenticator(
    etablissement_id: Any,
    *,
    par: Utilisateur,
    email: str,
    reference_demande: str,
    commentaire: str = "",
):
    """Réinitialisation de l'Authenticator du dernier administrateur par FYXOP (P4).

    Le super-admin ne voit pas la liste des utilisateurs : il désigne l'administrateur par
    l'adresse e-mail figurant sur la demande écrite signée. L'adresse doit être celle d'un
    administrateur ACTIF de CET établissement (sinon 404 / 409 ``PAS_ADMINISTRATEUR``). Les
    contrôles, la double journalisation et les notifications sont ceux de
    ``telephone.reinitialiser_par_fyxop`` (B6).
    """
    _exiger_plateforme(par)
    etablissement = etablissement_ou_404(etablissement_id)
    if etablissement.statut == StatutEtablissement.ARCHIVE:
        raise _archive()
    resolution = resoudre_connexion(email.strip())
    if resolution is None or resolution.etablissement_id != etablissement.id:
        raise ErreurApi(
            INTROUVABLE,
            "Aucun compte de cet établissement ne correspond à cette adresse.",
            statut=status.HTTP_404_NOT_FOUND,
        )
    with contexte_tenant(etablissement.id, utilisateur_id=par.pk):
        if resolution.utilisateur_id not in titulaires_administration():
            raise ErreurApi(
                PAS_ADMINISTRATEUR,
                "Ce compte n'est pas un administrateur actif de l'établissement.",
                statut=status.HTTP_409_CONFLICT,
            )
    return telephone.reinitialiser_par_fyxop(
        etablissement.id,
        resolution.utilisateur_id,
        par=par,
        reference_demande=reference_demande,
        commentaire=commentaire,
    )


# --- Super-administrateurs (commande creer_super_admin) ----------------------------------------


def _lien_configuration(utilisateur: Utilisateur) -> str:
    """Jeton REENROLEMENT_MFA (24 h) + e-mail après le commit ; renvoie le lien en clair."""
    _, clair = jetons.emettre_reenrolement(utilisateur)
    lien = emails.lien(f"/reenrolement/{clair}")
    emails.programmer(
        "configuration_super_admin",
        utilisateur.email,
        prenom=utilisateur.prenom,
        lien=lien,
        validite_h=int(jetons.VALIDITE_REENROLEMENT.total_seconds() // 3600),
    )
    return lien


def creer_super_admin(
    *, email: str, prenom: str, nom: str, mot_de_passe: str
) -> tuple[Utilisateur, str]:
    """Crée un super-administrateur ACTIF dont la MFA est à configurer au premier accès.

    - e-mail unique sur la plateforme (P1), sinon ``ErreurApi`` ``EMAIL_EXISTE`` ;
    - mot de passe validé par la politique (12 caractères, 3 catégories…), sinon
      ``django.core.exceptions.ValidationError`` ;
    - ``mfa_a_reconfigurer`` : la connexion répond ``REENROLEMENT_REQUIS`` tant que le
      parcours de réenrôlement (lien de 24 h envoyé par e-mail) n'est pas terminé ;
    - audit ``plateforme.super_admin.cree`` dans la chaîne de la plateforme.
    Renvoie ``(utilisateur, lien)`` ; le lien n'est ni journalisé ni enregistré en clair.
    """
    email = Utilisateur.objects.normalize_email((email or "").strip())
    if not email or not (prenom or "").strip() or not (nom or "").strip():
        raise ErreurApi(VALIDATION, "L'e-mail, le prénom et le nom sont obligatoires.")
    if resoudre_connexion(email) is not None:
        raise ErreurApi(
            EMAIL_EXISTE, "Cette adresse e-mail est déjà utilisée par un compte ALPHA.", statut=409
        )
    identifiant = uuid.uuid4()
    maintenant = timezone.now()
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=identifiant):
        utilisateur = Utilisateur(
            id=identifiant,
            email=email,
            prenom=prenom.strip(),
            nom=nom.strip(),
            est_super_admin=True,
            statut=StatutUtilisateur.ACTIF,
            mfa_a_reconfigurer=True,
            active_le=maintenant,
        )
        validate_password(mot_de_passe, user=utilisateur)
        utilisateur.set_password(mot_de_passe)
        utilisateur.mdp_modifie_le = maintenant
        utilisateur.save(force_insert=True)
        HistoriqueMotDePasse.objects.create(utilisateur=utilisateur, password=utilisateur.password)
        lien = _lien_configuration(utilisateur)
        journaliser(
            "plateforme.super_admin.cree",
            Categorie.SUPER_ADMIN,
            objet=utilisateur,
            objet_libelle=utilisateur.email,
            apres={
                **extraire_champs(utilisateur, ["email", "prenom", "nom", "statut"]),
                "mfa_a_reconfigurer": True,
                "lien_configuration_expire_le": maintenant + jetons.VALIDITE_REENROLEMENT,
            },
            detail="Super-administrateur FYXOP créé ; application d'authentification à "
            "configurer au premier accès",
            acteur=ACTEUR_COMMANDE,
            etablissement_id=None,
        )
    return utilisateur, lien


def nouveau_lien_super_admin(*, email: str) -> tuple[Utilisateur, str]:
    """Nouveau lien de configuration (l'ancien est annulé) pour un super-admin non configuré."""
    email = Utilisateur.objects.normalize_email((email or "").strip())
    resolution = resoudre_connexion(email) if email else None
    if resolution is None or not resolution.est_super_admin:
        raise ErreurApi(
            INTROUVABLE, "Aucun super-administrateur ne porte cette adresse.", statut=404
        )
    with contexte_tenant(
        None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=resolution.utilisateur_id
    ):
        utilisateur = Utilisateur.objects.select_for_update().get(pk=resolution.utilisateur_id)
        if utilisateur.statut != StatutUtilisateur.ACTIF or not utilisateur.mfa_a_reconfigurer:
            raise ErreurApi(
                "DEJA_CONFIGURE",
                "Ce compte n'attend pas de configuration de son application d'authentification.",
                statut=409,
            )
        lien = _lien_configuration(utilisateur)
        journaliser(
            "plateforme.super_admin.lien_renvoye",
            Categorie.SUPER_ADMIN,
            objet=utilisateur,
            objet_libelle=utilisateur.email,
            apres={"lien_configuration_expire_le": timezone.now() + jetons.VALIDITE_REENROLEMENT},
            detail="Nouveau lien de configuration (le précédent est annulé)",
            acteur=ACTEUR_COMMANDE,
            etablissement_id=None,
        )
    return utilisateur, lien


__all__ = [
    "CODE_EXISTE",
    "EMAIL_EXISTE",
    "PAS_ADMINISTRATEUR",
    "STATUT_INVALIDE",
    "SUSPENSION_DESACTIVEE",
    "controler_modification",
    "creer_super_admin",
    "etablissement_ou_404",
    "inviter_administrateur",
    "journaliser_double",
    "modifier_etablissement",
    "nouveau_lien_super_admin",
    "provisionner_etablissement",
    "reinitialiser_authenticator",
    "statistiques",
    "suspension_manuelle_active",
    "verifier_disponibilite",
]
