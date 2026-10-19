"""Téléphone perdu : signalement, réinitialisation, annulation (architecture § 4.5, décision P4).

Toutes les fonctions s'exécutent sous le contexte tenant de l'établissement de
l'intéressé et écrivent leur audit DANS la transaction de l'action.

- ``signaler`` : transaction unique — signature bloquée, Authenticator ACTIF →
  SUSPENDU, signalement OUVERT, TOUTES les sessions révoquées (``TELEPHONE_PERDU``),
  tâche « À traiter » pour le rôle administrateur, audit ``telephone.signale``,
  e-mails à l'intéressé et aux administrateurs ;
- ``reinitialiser`` : par un administrateur AUTRE que l'intéressé, après
  vérification d'identité hors ligne — Authenticator révoqué, codes de secours
  invalidés, ``mfa_a_reconfigurer``, signalement REINITIALISE, tâche terminée,
  jeton ``REENROLEMENT_MFA`` (24 h) envoyé, audit ``telephone.reinitialise`` ;
- ``reinitialiser_par_fyxop`` : décision P4 (aucun autre administrateur) —
  super-admin FYXOP, sur demande écrite signée + appel vidéo ; référence saisie,
  double journalisation (établissement + plateforme), autres administrateurs notifiés ;
- ``annuler`` : téléphone retrouvé — Authenticator réactivé, signature débloquée.

La signature reste bloquée jusqu'à la fin du réenrôlement (``parcours``).
"""

from __future__ import annotations

import datetime
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core.erreurs import ErreurApi
from alpha.organisation.codes_permission import PERMISSION_DERNIER_ADMIN
from alpha.organisation.models import Role
from alpha.organisation.services import titulaires_administration
from alpha.taches import services as taches
from alpha.taches.models import Action, Module
from alpha.tenancy.contexte import contexte_tenant

from . import emails, jetons, sessions
from .models import (
    AuthenticatorTOTP,
    CanalSignalement,
    CodeSecours,
    ModeVerification,
    MotifFinSession,
    SignalementTelephonePerdu,
    StatutAuthenticator,
    StatutSignalement,
    StatutUtilisateur,
    Utilisateur,
)

AUTO_TRAITEMENT_INTERDIT = "AUTO_TRAITEMENT_INTERDIT"
SIGNALEMENT_DEJA_TRAITE = "SIGNALEMENT_DEJA_TRAITE"
AUTRE_ADMINISTRATEUR_DISPONIBLE = "AUTRE_ADMINISTRATEUR_DISPONIBLE"
REFERENCE_OBLIGATOIRE = "REFERENCE_OBLIGATOIRE"

CHAMPS_UTILISATEUR = ["signature_bloquee", "mfa_a_reconfigurer"]


# --- Outils -----------------------------------------------------------------------------------


def un_jour_ouvre_apres(instant: datetime.datetime) -> datetime.datetime:
    """Même heure, le jour ouvré suivant (samedi et dimanche sautés ; heure de Dakar)."""
    local = timezone.localtime(instant) + datetime.timedelta(days=1)
    while local.weekday() >= 5:
        local += datetime.timedelta(days=1)
    return local


def signalement_ouvert(utilisateur_id: uuid.UUID) -> SignalementTelephonePerdu | None:
    return SignalementTelephonePerdu.objects.filter(
        utilisateur_id=utilisateur_id, statut=StatutSignalement.OUVERT
    ).first()


def role_administration() -> Role | None:
    """Rôle actif portant ``admin.utilisateurs`` (le premier dans l'ordre du catalogue)."""
    return (
        Role.objects.filter(actif=True, permissions__contains=[PERMISSION_DERNIER_ADMIN])
        .order_by("ordre", "libelle")
        .first()
    )


def autres_administrateurs(utilisateur_id: uuid.UUID) -> list[Utilisateur]:
    """Administrateurs actifs de l'établissement courant, hors l'intéressé."""
    ids = titulaires_administration() - {utilisateur_id}
    return list(Utilisateur.objects.filter(id__in=ids).order_by("nom", "prenom"))


def administrateurs_disponibles(utilisateur_id: uuid.UUID) -> list[Utilisateur]:
    """Autres administrateurs capables de traiter un signalement : compte actif et
    Authenticator ACTIF (le step-up TOTP l'exige), sans signalement ouvert."""
    autres = {a.pk: a for a in autres_administrateurs(utilisateur_id)}
    if not autres:
        return []
    equipes = set(
        AuthenticatorTOTP.objects.filter(
            utilisateur_id__in=list(autres), statut=StatutAuthenticator.ACTIF
        ).values_list("utilisateur_id", flat=True)
    )
    return [a for pk, a in autres.items() if pk in equipes]


def _figer(utilisateur: Utilisateur) -> dict:
    return extraire_champs(utilisateur, CHAMPS_UTILISATEUR)


def _relire(utilisateur: Utilisateur) -> Utilisateur:
    return Utilisateur.objects.select_for_update().get(pk=utilisateur.pk)


# --- Signalement -------------------------------------------------------------------------------


def signaler(
    utilisateur: Utilisateur, *, canal: str, acteur: Utilisateur | None = None
) -> SignalementTelephonePerdu:
    """Signale la perte du téléphone (§ 4.5, étape 2). Idempotent si un signalement est ouvert."""
    if canal not in CanalSignalement.values:
        raise ValueError(f"Canal inconnu : {canal!r}.")
    maintenant = timezone.now()
    with transaction.atomic():
        utilisateur = _relire(utilisateur)
        avant = _figer(utilisateur)
        utilisateur.signature_bloquee = True
        utilisateur.save(update_fields=["signature_bloquee", "modifie_le"])
        suspendus = AuthenticatorTOTP.objects.filter(
            utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.ACTIF
        ).update(statut=StatutAuthenticator.SUSPENDU)
        signalement = signalement_ouvert(utilisateur.pk)
        nouveau = signalement is None
        if nouveau:
            signalement = SignalementTelephonePerdu.objects.create(
                utilisateur=utilisateur, canal=canal, signale_le=maintenant
            )
        revoquees = sessions.revoquer_sessions(utilisateur, MotifFinSession.TELEPHONE_PERDU)
        role = role_administration() if nouveau else None
        if role is not None:
            taches.ouvrir(
                signalement,
                module=Module.ADMINISTRATION,
                action=Action.TRAITER,
                titre=f"Téléphone perdu · {utilisateur.nom_complet}",
                sous_titre="Vérifier l'identité puis réinitialiser l'application "
                "d'authentification",
                assigne_role=role,
                echeance=un_jour_ouvre_apres(maintenant),
                demandeur=utilisateur,
                lien=f"/administration/utilisateurs/{utilisateur.pk}",
                acteur=acteur or utilisateur,
            )
        journaliser(
            "telephone.signale",
            Categorie.SECURITE,
            objet=signalement,
            objet_libelle=utilisateur.nom_complet,
            avant=avant,
            apres={
                **_figer(utilisateur),
                "canal": canal,
                "authenticator_suspendu": bool(suspendus),
                "sessions_revoquees": revoquees,
                "deja_ouvert": not nouveau,
            },
            detail="Téléphone perdu signalé · signature bloquée, sessions révoquées",
            acteur=acteur or utilisateur,
        )
        emails.programmer(
            "telephone_signale",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(maintenant),
        )
        if nouveau:
            for admin in autres_administrateurs(utilisateur.pk):
                emails.programmer(
                    "telephone_signale_admin",
                    admin.email,
                    prenom=admin.prenom,
                    nom_utilisateur=utilisateur.nom_complet,
                    heure=emails.heure(maintenant),
                    lien=emails.lien(f"/administration/utilisateurs/{utilisateur.pk}"),
                )
    return signalement


# --- Réinitialisation --------------------------------------------------------------------------


def verifier_traitement(signalement: SignalementTelephonePerdu, par: Utilisateur) -> None:
    """403 ``AUTO_TRAITEMENT_INTERDIT`` / 409 ``SIGNALEMENT_DEJA_TRAITE`` (sans écriture)."""
    if signalement.utilisateur_id == par.pk:
        recours = not administrateurs_disponibles(signalement.utilisateur_id)
        raise ErreurApi(
            AUTO_TRAITEMENT_INTERDIT,
            "Vous ne pouvez pas traiter votre propre signalement : un autre administrateur "
            "doit vérifier votre identité."
            + (
                " Aucun autre administrateur n'est disponible : la direction de votre "
                "établissement doit adresser une demande écrite signée à FYXOP."
                if recours
                else ""
            ),
            statut=status.HTTP_403_FORBIDDEN,
            details={"recours_fyxop": recours},
        )
    if signalement.statut != StatutSignalement.OUVERT:
        raise ErreurApi(
            SIGNALEMENT_DEJA_TRAITE,
            "Ce signalement a déjà été traité.",
            statut=status.HTTP_409_CONFLICT,
            details={"statut": signalement.statut},
        )


def _reinitialiser(
    signalement: SignalementTelephonePerdu,
    *,
    par: Utilisateur,
    mode_verification: str,
    commentaire: str,
    reference_demande: str = "",
) -> tuple[SignalementTelephonePerdu, Utilisateur]:
    maintenant = timezone.now()
    utilisateur = _relire(signalement.utilisateur)
    avant_signalement = extraire_champs(signalement)
    avant = _figer(utilisateur)
    AuthenticatorTOTP.objects.filter(
        utilisateur_id=utilisateur.pk,
        statut__in=[
            StatutAuthenticator.ACTIF,
            StatutAuthenticator.SUSPENDU,
            StatutAuthenticator.EN_ATTENTE,
        ],
    ).update(statut=StatutAuthenticator.REVOQUE, revoque_le=maintenant)
    codes = CodeSecours.objects.filter(
        utilisateur_id=utilisateur.pk, utilise_le__isnull=True, invalide_le__isnull=True
    ).update(invalide_le=maintenant)
    utilisateur.mfa_a_reconfigurer = True
    utilisateur.signature_bloquee = True
    utilisateur.save(update_fields=["mfa_a_reconfigurer", "signature_bloquee", "modifie_le"])
    # Les codes de secours ne valent plus rien : les sessions ouvertes avec eux tombent aussi.
    revoquees = sessions.revoquer_sessions(utilisateur, MotifFinSession.TELEPHONE_PERDU)

    signalement.statut = StatutSignalement.REINITIALISE
    signalement.traite_par = par
    signalement.mode_verification = mode_verification
    signalement.commentaire = commentaire
    signalement.reference_demande = reference_demande
    signalement.traite_le = maintenant
    signalement.save()
    # Le super-admin FYXOP (P4) n'appartient pas à l'établissement : il n'est référencé
    # ni par la tâche ni par le jeton (clés « même établissement ») ; l'audit le nomme.
    du_tenant = None if par.est_super_admin else par
    taches.terminer(signalement, Action.TRAITER, par=du_tenant, resultat="Réinitialisé", acteur=par)

    _, clair = jetons.emettre_reenrolement(utilisateur, par=du_tenant)
    journaliser(
        "telephone.reinitialise",
        Categorie.SECURITE,
        objet=signalement,
        objet_libelle=utilisateur.nom_complet,
        avant={**avant_signalement, **avant},
        apres={
            **extraire_champs(signalement),
            **_figer(utilisateur),
            "codes_secours_invalides": codes,
            "sessions_revoquees": revoquees,
        },
        detail=f"Application d'authentification réinitialisée · vérification : "
        f"{ModeVerification(mode_verification).label}",
        acteur=par,
    )
    emails.programmer(
        "reenrolement",
        utilisateur.email,
        prenom=utilisateur.prenom,
        par="l'équipe FYXOP" if par.est_super_admin else par.nom_complet,
        lien=emails.lien(f"/reenrolement/{clair}"),
        validite_h=int(jetons.VALIDITE_REENROLEMENT.total_seconds() // 3600),
    )
    return signalement, utilisateur


def reinitialiser(
    signalement: SignalementTelephonePerdu,
    *,
    par: Utilisateur,
    mode_verification: str,
    commentaire: str = "",
) -> SignalementTelephonePerdu:
    """Réinitialisation par un administrateur de l'établissement (§ 4.5, étapes 4 et 5).

    L'appelant a vérifié la permission, l'absence d'auto-traitement
    (``verifier_traitement``) et le step-up TOTP de l'administrateur.
    """
    verifier_traitement(signalement, par)
    with transaction.atomic():
        signalement = SignalementTelephonePerdu.objects.select_for_update().get(pk=signalement.pk)
        verifier_traitement(signalement, par)
        signalement, _ = _reinitialiser(
            signalement, par=par, mode_verification=mode_verification, commentaire=commentaire
        )
    return signalement


def annuler(
    signalement: SignalementTelephonePerdu, *, par: Utilisateur, commentaire: str = ""
) -> SignalementTelephonePerdu:
    """Téléphone retrouvé : Authenticator SUSPENDU → ACTIF, signature débloquée, tâche terminée."""
    verifier_traitement(signalement, par)
    maintenant = timezone.now()
    with transaction.atomic():
        signalement = SignalementTelephonePerdu.objects.select_for_update().get(pk=signalement.pk)
        verifier_traitement(signalement, par)
        utilisateur = _relire(signalement.utilisateur)
        avant_signalement = extraire_champs(signalement)
        avant = _figer(utilisateur)
        reactives = AuthenticatorTOTP.objects.filter(
            utilisateur_id=utilisateur.pk, statut=StatutAuthenticator.SUSPENDU
        ).update(statut=StatutAuthenticator.ACTIF)
        if not utilisateur.mfa_a_reconfigurer:
            utilisateur.signature_bloquee = False
            utilisateur.save(update_fields=["signature_bloquee", "modifie_le"])
        signalement.statut = StatutSignalement.ANNULE
        signalement.traite_par = par
        signalement.commentaire = commentaire
        signalement.traite_le = maintenant
        signalement.save()
        taches.terminer(signalement, Action.TRAITER, par=par, resultat="Annulé", acteur=par)
        journaliser(
            "telephone.annule",
            Categorie.SECURITE,
            objet=signalement,
            objet_libelle=utilisateur.nom_complet,
            avant={**avant_signalement, **avant},
            apres={
                **extraire_champs(signalement),
                **_figer(utilisateur),
                "authenticator_reactive": bool(reactives),
            },
            detail="Signalement annulé · téléphone retrouvé",
            acteur=par,
        )
        emails.programmer(
            "telephone_retrouve",
            utilisateur.email,
            prenom=utilisateur.prenom,
            heure=emails.heure(maintenant),
        )
    return signalement


# --- Décision P4 : réinitialisation du dernier administrateur par FYXOP ------------------------


def reinitialiser_par_fyxop(
    etablissement_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
    *,
    par: Utilisateur,
    reference_demande: str,
    commentaire: str = "",
) -> SignalementTelephonePerdu:
    """Réinitialisation de l'Authenticator d'un administrateur par le super-admin FYXOP (P4).

    Conditions : ``par`` est super-administrateur ; référence de la demande écrite
    signée par la direction du client obligatoire ; identité vérifiée par appel vidéo
    avec pièce d'identité (``mode_verification = VISIO``) ; AUCUN autre administrateur
    DISPONIBLE (compte actif + Authenticator actif) dans l'établissement, sinon 409
    ``AUTRE_ADMINISTRATEUR_DISPONIBLE`` : la voie normale s'applique. Si aucun
    signalement n'est ouvert, il est créé (canal ADMIN).

    Journalisation double : ``telephone.reinitialise`` dans la chaîne de l'établissement
    et ``plateforme.telephone.reinitialise`` dans la chaîne de la plateforme. Les autres
    administrateurs actifs de l'établissement (indisponibles, par exemple eux-mêmes sans
    téléphone) sont notifiés par e-mail. Point d'entrée de la console FYXOP (B10), qui
    contrôle la permission ``SuperAdmin`` et le step-up avant l'appel.
    """
    if not par.est_super_admin:
        raise ErreurApi(
            "PERMISSION_REFUSEE",
            "Opération réservée au super-administrateur FYXOP.",
            statut=status.HTTP_403_FORBIDDEN,
        )
    reference = (reference_demande or "").strip()
    if not reference:
        raise ErreurApi(
            REFERENCE_OBLIGATOIRE,
            "Saisissez la référence de la demande écrite signée par la direction du client.",
            details={"reference_demande": ["Ce champ est obligatoire."]},
        )
    with contexte_tenant(etablissement_id, utilisateur_id=par.pk), transaction.atomic():
        utilisateur = (
            Utilisateur.objects.select_for_update()
            .filter(pk=utilisateur_id, statut=StatutUtilisateur.ACTIF)
            .first()
        )
        if utilisateur is None:
            raise ErreurApi("INTROUVABLE", "Utilisateur introuvable.", statut=404)
        if administrateurs_disponibles(utilisateur.pk):
            raise ErreurApi(
                AUTRE_ADMINISTRATEUR_DISPONIBLE,
                "Un autre administrateur actif peut traiter ce cas dans l'établissement.",
                statut=status.HTTP_409_CONFLICT,
            )
        signalement = signalement_ouvert(utilisateur.pk)
        if signalement is None:
            signalement = signaler(utilisateur, canal=CanalSignalement.ADMIN, acteur=par)
        signalement = SignalementTelephonePerdu.objects.select_for_update().get(pk=signalement.pk)
        signalement, utilisateur = _reinitialiser(
            signalement,
            par=par,
            mode_verification=ModeVerification.VISIO,
            commentaire=commentaire,
            reference_demande=reference[:120],
        )
        maintenant = timezone.now()
        destinataires = autres_administrateurs(utilisateur.pk)
        for admin in destinataires:
            emails.programmer(
                "reinitialisation_fyxop_admin",
                admin.email,
                prenom=admin.prenom,
                nom_utilisateur=utilisateur.nom_complet,
                heure=emails.heure(maintenant),
                reference=reference[:120],
            )
        journaliser(
            "plateforme.telephone.reinitialise",
            Categorie.SUPER_ADMIN,
            objet=signalement,
            objet_libelle=f"{utilisateur.nom_complet} · établissement {etablissement_id}",
            apres={
                "etablissement_id": etablissement_id,
                "reference_demande": reference[:120],
                "mode_verification": ModeVerification.VISIO,
                "administrateurs_notifies": len(destinataires),
            },
            detail="Réinitialisation du dernier administrateur sur demande écrite signée (P4)",
            acteur=par,
            etablissement_id=None,
        )
    return signalement


def _traite_par(signalement: SignalementTelephonePerdu) -> dict | None:
    if signalement.traite_par_id is None:
        return None
    # Le super-admin FYXOP (P4) n'est pas lisible sous le contexte de l'établissement.
    traite_par = Utilisateur.objects.filter(pk=signalement.traite_par_id).first()
    nom = traite_par.nom_complet if traite_par is not None else "FYXOP"
    return {"id": signalement.traite_par_id, "nom": nom}


def presenter(signalement: SignalementTelephonePerdu) -> dict:
    """Signalement pour l'API d'administration (lu sous le contexte de l'établissement)."""
    u = signalement.utilisateur
    return {
        "id": signalement.id,
        "utilisateur": {"id": u.id, "nom": u.nom_complet, "email": u.email},
        "canal": signalement.canal,
        "statut": signalement.statut,
        "signale_le": signalement.signale_le,
        "traite_par": _traite_par(signalement),
        "mode_verification": signalement.mode_verification or None,
        "reference_demande": signalement.reference_demande or None,
        "commentaire": signalement.commentaire,
        "traite_le": signalement.traite_le,
    }
