"""Services d'administration des comptes d'un établissement (tâche B7, § 4.3, § 5.5).

Invitation, modification, affectations, suspension, réactivation, déverrouillage,
renvoi d'invitation et révocation des sessions. Toutes les fonctions :

- s'exécutent sous le contexte tenant de l'établissement de l'administrateur ``par`` ;
- écrivent un événement d'audit dans la transaction de l'action (``avant``/``apres``
  restreints à ``AUDIT_CHAMPS``) ;
- respectent l'invariant « dernier administrateur » (``preserver_dernier_administrateur``).

Les envois d'e-mails (B6) et les sessions (B5) passent par ``alpha.comptes.raccordements``.
"""

from __future__ import annotations

import datetime
import functools
import secrets
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core.erreurs import ErreurApi
from alpha.organisation.models import AffectationRole, Role, UniteOrganisationnelle
from alpha.organisation.services import preserver_dernier_administrateur, verrouiller_etablissement
from alpha.tenancy.models import ParametresEtablissement

from . import raccordements
from .models import JetonUsageUnique, ObjetJeton, StatutUtilisateur, Utilisateur
from .resolution import empreinte_jeton, resoudre_connexion

EMAIL_EXISTE = "EMAIL_EXISTE"
ROLE_HORS_CATALOGUE = "ROLE_HORS_CATALOGUE"
STATUT_INVALIDE = "STATUT_INVALIDE"
UTILISATEUR_NON_INVITE = "UTILISATEUR_NON_INVITE"
AFFECTATION_EXISTE = "AFFECTATION_EXISTE"
AFFECTATION_TERMINEE = "AFFECTATION_TERMINEE"

#: Validité par défaut d'une invitation si l'établissement n'a pas de paramètres (P2).
VALIDITE_INVITATION_H_DEFAUT = 72


# --- Outils ---------------------------------------------------------------------------------


def role_du_catalogue(role_id: Any) -> Role:
    """Rôle actif du catalogue de l'établissement courant, sinon 400 ``ROLE_HORS_CATALOGUE``."""
    role = Role.objects.filter(id=role_id, actif=True).first()
    if role is None:
        raise ErreurApi(
            ROLE_HORS_CATALOGUE,
            "Ce rôle n'existe pas ou n'est pas actif dans le catalogue de l'établissement.",
            details={"role_id": ["Rôle inconnu ou inactif."]},
        )
    return role


def _verifier_unite(unite: UniteOrganisationnelle | None) -> None:
    if unite is not None and not unite.actif:
        raise ErreurApi(
            "VALIDATION",
            "Certaines données sont invalides.",
            details={"unite_id": ["Cette unité est désactivée."]},
        )


def _annuler_jetons(utilisateur: Utilisateur, objets: list[str] | None = None) -> int:
    """Annule les jetons en cours (non utilisés, non annulés) de l'utilisateur."""
    qs = JetonUsageUnique.objects.filter(
        utilisateur=utilisateur, utilise_le__isnull=True, annule_le__isnull=True
    )
    if objets is not None:
        qs = qs.filter(objet__in=objets)
    return qs.update(annule_le=timezone.now())


def _emettre_invitation(utilisateur: Utilisateur, par: Utilisateur) -> JetonUsageUnique:
    """Nouveau jeton INVITATION (les précédents sont annulés) ; e-mail après commit (B6)."""
    _annuler_jetons(utilisateur, [ObjetJeton.INVITATION])
    parametres = ParametresEtablissement.objects.filter(
        etablissement_id=utilisateur.etablissement_id
    ).first()
    validite = parametres.validite_invitation_h if parametres else VALIDITE_INVITATION_H_DEFAUT
    clair = secrets.token_urlsafe(32)
    jeton = JetonUsageUnique.objects.create(
        utilisateur=utilisateur,
        objet=ObjetJeton.INVITATION,
        jeton_hash=empreinte_jeton(clair),
        expire_le=timezone.now() + datetime.timedelta(hours=validite),
        cree_par=par,
    )
    transaction.on_commit(
        functools.partial(
            raccordements.envoyer_invitation,
            utilisateur.etablissement_id,
            utilisateur.id,
            clair,
            jeton.expire_le,
        )
    )
    return jeton


# --- Invitation -------------------------------------------------------------------------------


def inviter(
    *,
    par: Utilisateur,
    email: str,
    prenom: str,
    nom: str,
    role_id: Any,
    unite: UniteOrganisationnelle | None = None,
    responsable: Utilisateur | None = None,
    telephone_mobile: str | None = None,
) -> Utilisateur:
    """Crée un utilisateur INVITE, son affectation principale et un jeton d'invitation (§ 4.3).

    - rôle actif du catalogue, sinon 400 ``ROLE_HORS_CATALOGUE`` ;
    - e-mail unique sur TOUTE la plateforme (P1) : contrôle par ``alpha_resoudre_connexion``
      (seul passage autorisé entre établissements), sinon 409 ``EMAIL_EXISTE`` ;
    - l'e-mail d'invitation part après le commit (``raccordements.envoyer_invitation``, B6).

    TODO B9 : créer les ``preferences_notification`` par défaut (modèle non encore livré).
    """
    role = role_du_catalogue(role_id)
    _verifier_unite(unite)
    email = Utilisateur.objects.normalize_email(email.strip())
    if resoudre_connexion(email) is not None:
        raise _email_existe()
    try:
        with transaction.atomic():
            utilisateur = Utilisateur.objects.create_user(
                email=email,
                prenom=prenom.strip(),
                nom=nom.strip(),
                telephone_mobile=telephone_mobile or None,
                responsable=responsable,
                statut=StatutUtilisateur.INVITE,
                cree_par=par,
            )
    except IntegrityError:  # course entre deux invitations de la même adresse
        raise _email_existe() from None
    affectation = AffectationRole.objects.create(
        utilisateur=utilisateur, role=role, unite=unite, principal=True, cree_par=par
    )
    jeton = _emettre_invitation(utilisateur, par)
    journaliser(
        "utilisateur.invite",
        Categorie.PARAMETRAGE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        apres={
            **extraire_champs(utilisateur),
            "affectation": extraire_champs(affectation),
            "invitation_expire_le": jeton.expire_le,
        },
        detail=f"Invitation comme « {role.libelle} »",
        acteur=par,
    )
    return utilisateur


def _email_existe() -> ErreurApi:
    return ErreurApi(
        EMAIL_EXISTE,
        "Cette adresse e-mail est déjà utilisée par un compte ALPHA.",
        statut=409,
        details={"email": ["Adresse déjà utilisée."]},
    )


def renvoyer_invitation(utilisateur: Utilisateur, *, par: Utilisateur) -> JetonUsageUnique:
    """Nouveau lien d'invitation (l'ancien est annulé) ; 409 si le compte n'est pas INVITE."""
    if utilisateur.statut != StatutUtilisateur.INVITE:
        raise ErreurApi(
            UTILISATEUR_NON_INVITE,
            "Seul un compte en attente d'activation peut recevoir une nouvelle invitation.",
            statut=409,
        )
    jeton = _emettre_invitation(utilisateur, par)
    journaliser(
        "utilisateur.invite",
        Categorie.PARAMETRAGE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        apres={"invitation_expire_le": jeton.expire_le},
        detail="Invitation renvoyée (le lien précédent est annulé)",
        acteur=par,
    )
    return jeton


# --- Modification -----------------------------------------------------------------------------


def modifier(utilisateur: Utilisateur, *, par: Utilisateur, **champs: Any) -> Utilisateur:
    """Modifie prénom, nom, téléphone ou responsable (``utilisateur.modifie``)."""
    if "telephone_mobile" in champs:
        champs["telephone_mobile"] = champs["telephone_mobile"] or None
    modifies = [c for c, v in champs.items() if getattr(utilisateur, c) != v]
    if not modifies:
        return utilisateur
    avant = extraire_champs(utilisateur, modifies)
    for cle, valeur in champs.items():
        setattr(utilisateur, cle, valeur)
    utilisateur.save()
    journaliser(
        "utilisateur.modifie",
        Categorie.PARAMETRAGE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        avant=avant,
        apres=extraire_champs(utilisateur, modifies),
        acteur=par,
    )
    return utilisateur


# --- Affectations -----------------------------------------------------------------------------


def ajouter_affectation(
    utilisateur: Utilisateur,
    *,
    par: Utilisateur,
    role_id: Any,
    unite: UniteOrganisationnelle | None = None,
    principal: bool = False,
) -> AffectationRole:
    """Ajoute une habilitation (``affectation.creee``).

    ``principal=True`` : l'ancienne affectation principale en cours devient secondaire.
    Même rôle sur la même unité déjà en cours : 409 ``AFFECTATION_EXISTE``.
    """
    role = role_du_catalogue(role_id)
    _verifier_unite(unite)
    en_cours = AffectationRole.objects.filter(utilisateur=utilisateur, fin__isnull=True)
    if en_cours.filter(role=role, unite=unite).exists():
        raise ErreurApi(
            AFFECTATION_EXISTE,
            "Cet utilisateur détient déjà ce rôle sur ce périmètre.",
            statut=409,
        )
    if principal:
        en_cours.filter(principal=True).update(principal=False)
    try:
        with transaction.atomic():
            affectation = AffectationRole.objects.create(
                utilisateur=utilisateur, role=role, unite=unite, principal=principal, cree_par=par
            )
    except IntegrityError:
        raise ErreurApi(
            AFFECTATION_EXISTE,
            "Cet utilisateur détient déjà ce rôle sur ce périmètre.",
            statut=409,
        ) from None
    journaliser(
        "affectation.creee",
        Categorie.PARAMETRAGE,
        objet=affectation,
        objet_libelle=f"{utilisateur.nom_complet} · {role.libelle}",
        apres=extraire_champs(affectation),
        acteur=par,
    )
    return affectation


def terminer_affectation(affectation: AffectationRole, *, par: Utilisateur) -> AffectationRole:
    """Termine une habilitation à la date du jour (``affectation.terminee``).

    L'affectation cesse aussitôt d'ouvrir des droits (``en_cours()`` exige ``fin`` NULL).
    Refus 409 ``DERNIER_ADMINISTRATEUR`` si elle portait le dernier administrateur actif.
    """
    if affectation.fin is not None:
        raise ErreurApi(AFFECTATION_TERMINEE, "Cette affectation est déjà terminée.", statut=409)
    avant = extraire_champs(affectation, ["fin", "principal"])
    with preserver_dernier_administrateur():
        affectation.fin = max(timezone.localdate(), affectation.debut)
        affectation.save(update_fields=["fin"])
    journaliser(
        "affectation.terminee",
        Categorie.PARAMETRAGE,
        objet=affectation,
        objet_libelle=f"{affectation.utilisateur.nom_complet} · {affectation.role.libelle}",
        avant=avant,
        apres=extraire_champs(affectation, ["fin", "principal"]),
        acteur=par,
    )
    return affectation


# --- Cycle de vie du compte ---------------------------------------------------------------------


def suspendre(utilisateur: Utilisateur, *, par: Utilisateur, motif: str) -> int:
    """Suspend un compte ACTIF (``utilisateur.suspendu``) ; renvoie le nombre de sessions révoquées.

    Annule les liens en cours (réinitialisation, réenrôlement) et révoque les sessions.
    409 ``STATUT_INVALIDE`` si le compte n'est pas actif ; 409 ``DERNIER_ADMINISTRATEUR``.
    """
    if utilisateur.statut != StatutUtilisateur.ACTIF:
        raise ErreurApi(STATUT_INVALIDE, "Seul un compte actif peut être suspendu.", statut=409)
    avant = extraire_champs(utilisateur, ["statut"])
    with preserver_dernier_administrateur():
        utilisateur.statut = StatutUtilisateur.SUSPENDU
        utilisateur.save(update_fields=["statut", "modifie_le"])
    _annuler_jetons(utilisateur)
    revoquees = raccordements.revoquer_sessions(utilisateur.id, motif="REVOCATION_ADMIN")
    journaliser(
        "utilisateur.suspendu",
        Categorie.SECURITE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        avant=avant,
        apres=extraire_champs(utilisateur, ["statut"]),
        detail=f"Motif : {motif}",
        acteur=par,
    )
    return revoquees


def reactiver(utilisateur: Utilisateur, *, par: Utilisateur) -> Utilisateur:
    """Réactive un compte SUSPENDU (``utilisateur.reactive``) ; 409 ``STATUT_INVALIDE`` sinon."""
    if utilisateur.statut != StatutUtilisateur.SUSPENDU:
        raise ErreurApi(STATUT_INVALIDE, "Seul un compte suspendu peut être réactivé.", statut=409)
    verrouiller_etablissement()
    avant = extraire_champs(utilisateur, ["statut"])
    utilisateur.statut = StatutUtilisateur.ACTIF
    utilisateur.save(update_fields=["statut", "modifie_le"])
    journaliser(
        "utilisateur.reactive",
        Categorie.SECURITE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        avant=avant,
        apres=extraire_champs(utilisateur, ["statut"]),
        acteur=par,
    )
    return utilisateur


CHAMPS_VERROUILLAGE = [
    "echecs_connexion",
    "verrouille_jusqua",
    "verrouillages_24h",
    "bloque_par_admin",
]


def deverrouiller(utilisateur: Utilisateur, *, par: Utilisateur) -> Utilisateur:
    """Lève le verrouillage et le blocage administrateur (``utilisateur.deverrouille``, § 4.2).

    Remet à zéro les compteurs de ``utilisateur`` (champs du § 2.2, déjà présents). Les
    compteurs de limitation de débit Redis (B5) ne sont pas concernés : ils expirent seuls.
    """
    avant = extraire_champs(utilisateur, CHAMPS_VERROUILLAGE)
    utilisateur.echecs_connexion = 0
    utilisateur.verrouille_jusqua = None
    utilisateur.verrouillages_24h = 0
    utilisateur.bloque_par_admin = False
    utilisateur.save(update_fields=[*CHAMPS_VERROUILLAGE, "modifie_le"])
    journaliser(
        "utilisateur.deverrouille",
        Categorie.SECURITE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        avant=avant,
        apres=extraire_champs(utilisateur, CHAMPS_VERROUILLAGE),
        acteur=par,
    )
    return utilisateur


def revoquer_sessions(utilisateur: Utilisateur, *, par: Utilisateur) -> int:
    """Révoque toutes les sessions de l'utilisateur (``auth.session.revoquee``)."""
    revoquees = raccordements.revoquer_sessions(utilisateur.id, motif="REVOCATION_ADMIN")
    journaliser(
        "auth.session.revoquee",
        Categorie.SECURITE,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        apres={"revoquees": revoquees},
        detail="Révocation de toutes les sessions par un administrateur",
        acteur=par,
    )
    return revoquees


def est_verrouille(utilisateur: Utilisateur) -> bool:
    """Compte bloqué par l'administrateur ou verrouillé temporairement."""
    return utilisateur.bloque_par_admin or (
        utilisateur.verrouille_jusqua is not None and utilisateur.verrouille_jusqua > timezone.now()
    )
