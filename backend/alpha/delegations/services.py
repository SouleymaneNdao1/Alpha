"""Absences et délégations : règles métier (architecture § 2.2, § 5.3, § 5.4, décision P5).

Décision P5 (15/10/2026) :
- valideur = responsable hiérarchique (``utilisateur.responsable``, s'il est ACTIF),
  sinon un administrateur (titulaire ACTIF de ``admin.absences``) ;
- le délégataire détient des pouvoirs AU MOINS ÉGAUX à ceux de l'absent
  (``alpha.organisation.pouvoirs``, affectations en cours) ;
- pas de sous-délégation : ni l'absent ne peut redéléguer ce qu'il a lui-même reçu
  sur la période, ni le délégataire ne peut être lui-même délégant (absent) sur la
  période ; la visibilité par délégation n'est jamais transitive ;
- délégation toujours bornée : ``debut`` < ``fin``, ``fin`` dans le futur, durée
  maximale ``DUREE_MAX``.

Toutes les fonctions s'exécutent sous le contexte tenant de l'appelant, dans sa
transaction, et journalisent (``absence.soumise|validee|refusee|annulee``,
``delegation.active|terminee``, § 6.1).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.core.erreurs import PERMISSION_REFUSEE, VALIDATION, ErreurApi
from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.models import AffectationRole
from alpha.organisation.permissions import permissions_de
from alpha.organisation.pouvoirs import Pouvoirs, parents_des_unites
from alpha.taches import services as taches
from alpha.taches.models import Action, Module, TypeEcheance
from alpha.taches.visibilite import delegants_effectifs

from . import signaux
from .models import (
    STATUTS_EN_COURS,
    Absence,
    Delegation,
    MotifAbsence,
    OrigineDelegation,
    StatutAbsence,
    StatutDelegation,
)

#: Durée maximale d'une absence (et donc d'une délégation) : une délégation est bornée.
DUREE_MAX = datetime.timedelta(days=366)

# Codes d'erreur métier (§ 5 : 400 validation, 403 permission, 409 conflit).
DELEGATAIRE_INVALIDE = "DELEGATAIRE_INVALIDE"
ROLE_NON_DETENU = "ROLE_NON_DETENU"
POUVOIRS_INSUFFISANTS = "POUVOIRS_INSUFFISANTS"
SOUS_DELEGATION_INTERDITE = "SOUS_DELEGATION_INTERDITE"
CHEVAUCHEMENT = "CHEVAUCHEMENT"
AUCUN_VALIDEUR = "AUCUN_VALIDEUR"
STATUT_INVALIDE = "STATUT_INVALIDE"
ABSENCE_EXPIREE = "ABSENCE_EXPIREE"

PERMISSION_ABSENCES = CodePermission.ADMIN_ABSENCES.value


def _conflit(code: str, message: str, details: dict | None = None) -> ErreurApi:
    return ErreurApi(code, message, statut=status.HTTP_409_CONFLICT, details=details)


def _chevauche(debut: datetime.datetime, fin: datetime.datetime) -> Q:
    """Périodes [debut, fin) qui chevauchent [d, f) : debut < f et fin > d."""
    return Q(debut__lt=fin, fin__gt=debut)


# --- Valideur -------------------------------------------------------------------------------


def titulaires_permission(code: str):
    """Utilisateurs ACTIFS titulaires de ``code`` (affectation en cours, rôle actif)."""
    ids = (
        AffectationRole.objects.en_cours()
        .filter(role__actif=True, role__permissions__contains=[code])
        .values("utilisateur_id")
    )
    return Utilisateur.objects.filter(pk__in=ids, statut=StatutUtilisateur.ACTIF)


def designer_valideur(utilisateur: Utilisateur) -> Utilisateur | None:
    """Responsable hiérarchique actif, sinon le premier administrateur des absences (P5)."""
    if utilisateur.responsable_id and utilisateur.responsable_id != utilisateur.pk:
        responsable = Utilisateur.objects.filter(
            pk=utilisateur.responsable_id, statut=StatutUtilisateur.ACTIF
        ).first()
        if responsable is not None:
            return responsable
    return (
        titulaires_permission(PERMISSION_ABSENCES)
        .exclude(pk=utilisateur.pk)
        .order_by("nom", "prenom", "id")
        .first()
    )


def autorisation_decision(absence: Absence, par: Utilisateur) -> tuple[bool, uuid.UUID | None]:
    """(autorisé, pour_compte_de) : ``par`` peut-il valider ou refuser cette absence ?

    Autorisés : le valideur désigné, un titulaire de ``admin.absences``, ou le
    délégataire effectif du valideur (délégation sans limite de rôle), qui agit
    alors pour son compte. Jamais l'absent lui-même.
    """
    if par.pk == absence.utilisateur_id:
        return False, None
    if par.pk == absence.valideur_id:
        return True, None
    if PERMISSION_ABSENCES in permissions_de(par.pk):
        return True, None
    if absence.valideur_id in delegants_effectifs(par.pk, tous_roles_seulement=True):
        return True, absence.valideur_id
    return False, None


def peut_consulter(absence: Absence, utilisateur: Utilisateur) -> bool:
    """Demandeur, valideur, ``admin.absences`` ou délégataire effectif du valideur (§ 5.4)."""
    if utilisateur.pk in (absence.utilisateur_id, absence.valideur_id):
        return True
    return autorisation_decision(absence, utilisateur)[0]


# --- Contrôles de la délégation (P5) ------------------------------------------------------------


def pouvoirs_de_plusieurs(utilisateurs: list[uuid.UUID]) -> dict[uuid.UUID, Pouvoirs]:
    """``Pouvoirs.de`` pour plusieurs utilisateurs en une requête (liste des délégataires)."""
    habilitations: dict[uuid.UUID, set] = {u: set() for u in utilisateurs}
    permissions: dict[uuid.UUID, set] = {u: set() for u in utilisateurs}
    for u_id, r_id, unite_id, perms in (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id__in=utilisateurs, role__actif=True)
        .values_list("utilisateur_id", "role_id", "unite_id", "role__permissions")
    ):
        habilitations[u_id].add((r_id, unite_id))
        permissions[u_id].update(perms or ())
    return {
        u: Pouvoirs(frozenset(habilitations[u]), frozenset(permissions[u])) for u in utilisateurs
    }


def verifier_delegation(
    delegant: Utilisateur,
    delegataire_id: Any,
    role_id: Any,
    debut: datetime.datetime,
    fin: datetime.datetime,
) -> Utilisateur:
    """Contrôle P5 ; renvoie le délégataire. Lève ``ErreurApi`` (400 ou 409) sinon."""
    delegataire = (
        Utilisateur.objects.filter(pk=delegataire_id, statut=StatutUtilisateur.ACTIF).first()
        if delegataire_id
        else None
    )
    if delegataire is None or delegataire.pk == delegant.pk:
        raise ErreurApi(
            DELEGATAIRE_INVALIDE,
            "Choisissez comme délégataire un autre utilisateur actif de votre établissement.",
            details={"delegataire_id": ["Délégataire invalide."]},
        )
    if role_id is not None and not (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id=delegant.pk, role_id=role_id, role__actif=True)
        .exists()
    ):
        raise ErreurApi(
            ROLE_NON_DETENU,
            "Vous ne pouvez déléguer qu'un rôle que vous détenez.",
            details={"role_id": ["Rôle non détenu."]},
        )

    en_cours = Q(statut__in=STATUTS_EN_COURS) & _chevauche(debut, fin)
    if Delegation.objects.filter(en_cours, delegataire_id=delegant.pk).exists():
        raise _conflit(
            SOUS_DELEGATION_INTERDITE,
            "Vous êtes vous-même délégataire sur cette période : une délégation reçue "
            "ne peut pas être déléguée à nouveau.",
        )
    if Delegation.objects.filter(en_cours, delegant_id=delegataire.pk).exists():
        raise _conflit(
            SOUS_DELEGATION_INTERDITE,
            "Ce délégataire a lui-même délégué ses pouvoirs sur cette période : "
            "choisissez une autre personne.",
        )

    parents = parents_des_unites()
    requis = Pouvoirs.de(delegant.pk, role_id=_uuid(role_id))
    detenus = Pouvoirs.de(delegataire.pk)
    if not detenus.couvre(requis, parents):
        raise _conflit(
            POUVOIRS_INSUFFISANTS,
            "Le délégataire doit détenir des pouvoirs au moins égaux aux vôtres "
            "(mêmes rôles sur le même périmètre, mêmes permissions).",
            details={"permissions_manquantes": sorted(requis.permissions - detenus.permissions)},
        )
    return delegataire


def _uuid(valeur: Any) -> uuid.UUID | None:
    if valeur is None or valeur == "":
        return None
    return valeur if isinstance(valeur, uuid.UUID) else uuid.UUID(str(valeur))


def verifier_periode(debut: datetime.datetime, fin: datetime.datetime) -> None:
    erreurs: dict[str, list[str]] = {}
    if fin <= debut:
        erreurs["fin"] = ["La fin doit être postérieure au début."]
    elif fin <= timezone.now():
        erreurs["fin"] = ["La fin doit être dans le futur."]
    elif fin - debut > DUREE_MAX:
        erreurs["fin"] = [f"Une absence dure au plus {DUREE_MAX.days} jours."]
    if erreurs:
        raise ErreurApi(VALIDATION, "Certaines données sont invalides.", details=erreurs)


# --- Journalisation ---------------------------------------------------------------------------


def _libelle_absence(absence: Absence) -> str:
    return f"Absence de {absence.utilisateur.nom_complet} du {_date(absence.debut)}"


def _date(instant: datetime.datetime) -> str:
    return timezone.localtime(instant).strftime("%d/%m/%Y")


def _journaliser_absence(action: str, absence: Absence, *, avant=None, acteur=None, detail=""):
    categorie = (
        Categorie.DECISION
        if action in ("absence.validee", "absence.refusee")
        else Categorie.MODIFICATION
    )
    journaliser(
        action,
        categorie,
        objet=absence,
        objet_libelle=_libelle_absence(absence),
        avant=avant,
        apres=extraire_champs(absence),
        acteur=acteur,
        detail=detail,
    )


def _journaliser_delegation(
    action: str, delegation: Delegation, *, avant=None, acteur=None, detail=""
):
    journaliser(
        action,
        Categorie.MODIFICATION,
        objet=delegation,
        objet_libelle=(
            f"Délégation de {delegation.delegant.nom_complet} "
            f"à {delegation.delegataire.nom_complet}"
        ),
        avant=avant,
        apres=extraire_champs(delegation),
        acteur=acteur,
        detail=detail,
    )


# --- Cycle de vie d'une absence -----------------------------------------------------------------


def soumettre_absence(
    utilisateur: Utilisateur,
    *,
    debut: datetime.datetime,
    fin: datetime.datetime,
    motif: str,
    delegataire_id: Any,
    role_id: Any = None,
    commentaire: str = "",
    acteur: Utilisateur | None = None,
) -> Absence:
    """Crée l'absence (SOUMISE), sa délégation (EN_ATTENTE) et la tâche du valideur.

    ``acteur`` : auteur de la déclaration s'il n'est pas l'absent (administrateur qui
    déclare pour le compte d'un utilisateur, ``POST /admin/absences``, B13). Les règles
    (période, chevauchement, P5, valideur) sont les mêmes ; seul l'auteur journalisé change.
    """
    auteur = acteur or utilisateur
    if motif not in MotifAbsence.values:
        raise ErreurApi(VALIDATION, "Certaines données sont invalides.", details={"motif": ["?"]})
    verifier_periode(debut, fin)
    if (
        Absence.objects.filter(
            utilisateur_id=utilisateur.pk,
            statut__in=(StatutAbsence.SOUMISE, StatutAbsence.VALIDEE),
        )
        .filter(_chevauche(debut, fin))
        .exists()
    ):
        raise _conflit(CHEVAUCHEMENT, "Une absence est déjà déclarée sur cette période.")
    delegataire = verifier_delegation(utilisateur, delegataire_id, _uuid(role_id), debut, fin)
    valideur = designer_valideur(utilisateur)
    if valideur is None:
        raise _conflit(
            AUCUN_VALIDEUR,
            "Aucun responsable ni administrateur ne peut valider votre absence. "
            "Contactez votre administrateur.",
        )

    absence = Absence(
        utilisateur=utilisateur,
        debut=debut,
        fin=fin,
        motif=motif,
        commentaire=commentaire,
        valideur=valideur,
    )
    delegation = Delegation(
        origine=OrigineDelegation.ABSENCE,
        absence=absence,
        delegant=utilisateur,
        delegataire=delegataire,
        role_id=_uuid(role_id),
        debut=debut,
        fin=fin,
    )
    try:
        with transaction.atomic():
            absence.save()
            delegation.save()
    except IntegrityError as exc:
        # Contrainte d'exclusion (délégation en cours sur la même période, accès concurrent).
        if "delegation_sans_chevauchement" in str(exc):
            raise _conflit(CHEVAUCHEMENT, "Une délégation existe déjà sur cette période.") from exc
        raise

    taches.ouvrir(
        absence,
        module=Module.COMPTE,
        action=Action.VALIDER,
        titre=f"Absence · {utilisateur.nom_complet}",
        sous_titre=(
            f"{MotifAbsence(motif).label} du {_date(debut)} au {_date(fin)}"
            f" · délégataire {delegataire.nom_complet}"
        ),
        echeance=debut,
        type_echeance=TypeEcheance.AVANT,
        assigne_utilisateur=valideur,
        demandeur=utilisateur,
        lien=f"/absences/{absence.pk}",
        acteur=auteur,
    )
    detail = f"Délégataire : {delegataire.nom_complet}"
    if auteur.pk != utilisateur.pk:
        detail += f" · déclarée par {auteur.nom_complet} pour le compte de l'absent"
    _journaliser_absence("absence.soumise", absence, acteur=auteur, detail=detail)
    signaux.absence_soumise.send(sender=Absence, absence=absence, delegation=delegation)
    return absence


def delegation_de(absence: Absence) -> Delegation | None:
    """Délégation (la plus récente) rattachée à l'absence."""
    return (
        Delegation.objects.select_related("delegant", "delegataire", "role")
        .filter(absence_id=absence.pk)
        .order_by("-cree_le")
        .first()
    )


def _verrouiller(absence: Absence) -> Absence:
    return Absence.objects.select_for_update().select_related("utilisateur").get(pk=absence.pk)


def _exiger_decision(absence: Absence, par: Utilisateur) -> uuid.UUID | None:
    autorise, pour_compte_de = autorisation_decision(absence, par)
    if not autorise:
        raise ErreurApi(
            PERMISSION_REFUSEE,
            "Vous ne pouvez pas décider de cette absence.",
            statut=status.HTTP_403_FORBIDDEN,
        )
    if absence.statut != StatutAbsence.SOUMISE:
        raise _conflit(STATUT_INVALIDE, "Cette absence a déjà été traitée.")
    return pour_compte_de


def valider_absence(absence: Absence, par: Utilisateur) -> Absence:
    """Valide l'absence : délégation ACTIVE, tâche du valideur terminée (§ 5.4)."""
    absence = _verrouiller(absence)
    pour_compte_de = _exiger_decision(absence, par)
    maintenant = timezone.now()
    if absence.fin <= maintenant:
        raise _conflit(
            ABSENCE_EXPIREE, "Cette absence est terminée : elle ne peut plus être validée."
        )
    delegation = delegation_de(absence)
    if delegation is not None and delegation.statut == StatutDelegation.EN_ATTENTE:
        # Les pouvoirs ont pu changer depuis la soumission (P5).
        verifier_delegation(
            absence.utilisateur,
            delegation.delegataire_id,
            delegation.role_id,
            delegation.debut,
            delegation.fin,
        )

    avant = extraire_champs(absence, ["statut", "valideur", "decide_le"])
    absence.statut = StatutAbsence.VALIDEE
    absence.valideur = par
    absence.decide_le = maintenant
    absence.save(update_fields=["statut", "valideur", "decide_le"])
    _journaliser_absence("absence.validee", absence, avant=avant, acteur=par)

    if delegation is not None and delegation.statut == StatutDelegation.EN_ATTENTE:
        delegation.statut = StatutDelegation.ACTIVE
        delegation.save(update_fields=["statut"])
        if delegation.debut <= maintenant:
            activer(delegation, maintenant, acteur=par)
    taches.terminer(
        absence,
        Action.VALIDER,
        par=par,
        resultat=StatutAbsence.VALIDEE,
        pour_compte_de=pour_compte_de,
    )
    signaux.absence_decidee.send(sender=Absence, absence=absence, delegation=delegation)
    return absence


def refuser_absence(absence: Absence, par: Utilisateur, motif: str) -> Absence:
    absence = _verrouiller(absence)
    pour_compte_de = _exiger_decision(absence, par)
    if not (motif or "").strip():
        raise ErreurApi(
            VALIDATION, "Certaines données sont invalides.", details={"motif": ["Obligatoire."]}
        )
    avant = extraire_champs(absence, ["statut", "valideur", "decide_le"])
    absence.statut = StatutAbsence.REFUSEE
    absence.valideur = par
    absence.decide_le = timezone.now()
    absence.motif_refus = motif.strip()
    absence.save(update_fields=["statut", "valideur", "decide_le", "motif_refus"])
    _journaliser_absence("absence.refusee", absence, avant=avant, acteur=par, detail=motif.strip())
    delegation = delegation_de(absence)
    if delegation is not None and delegation.statut in STATUTS_EN_COURS:
        delegation.statut = StatutDelegation.REFUSEE
        delegation.save(update_fields=["statut"])
    taches.terminer(
        absence,
        Action.VALIDER,
        par=par,
        resultat=StatutAbsence.REFUSEE,
        pour_compte_de=pour_compte_de,
    )
    signaux.absence_decidee.send(sender=Absence, absence=absence, delegation=delegation)
    return absence


def annuler_absence(absence: Absence, par: Utilisateur) -> Absence:
    """Annulation par l'absent (§ 5.3).

    Avant le début : absence ANNULEE, délégation ANNULEE, tâche du valideur annulée.
    Pendant l'absence validée : ``fin`` est avancée à maintenant (l'absence reste
    VALIDEE) et la délégation est TERMINEE.
    """
    absence = _verrouiller(absence)
    if absence.utilisateur_id != par.pk:
        raise ErreurApi(
            PERMISSION_REFUSEE,
            "Seul l'auteur de l'absence peut l'annuler.",
            statut=status.HTTP_403_FORBIDDEN,
        )
    maintenant = timezone.now()
    delegation = delegation_de(absence)
    avant = extraire_champs(absence, ["statut", "fin"])

    if absence.statut == StatutAbsence.SOUMISE or (
        absence.statut == StatutAbsence.VALIDEE and maintenant <= absence.debut
    ):
        absence.statut = StatutAbsence.ANNULEE
        absence.save(update_fields=["statut"])
        if delegation is not None and delegation.statut in STATUTS_EN_COURS:
            delegation.statut = StatutDelegation.ANNULEE
            delegation.save(update_fields=["statut"])
        taches.annuler(absence, par=par)
    elif absence.statut == StatutAbsence.VALIDEE and maintenant < absence.fin:
        absence.fin = maintenant
        absence.save(update_fields=["fin"])
        if delegation is not None and delegation.statut == StatutDelegation.ACTIVE:
            delegation.fin = maintenant
            delegation.save(update_fields=["fin"])
            terminer(delegation, maintenant, acteur=par)
    else:
        raise _conflit(STATUT_INVALIDE, "Cette absence ne peut plus être annulée.")
    _journaliser_absence("absence.annulee", absence, avant=avant, acteur=par)
    signaux.absence_annulee.send(sender=Absence, absence=absence, delegation=delegation)
    return absence


# --- Révocation par un administrateur (B13) --------------------------------------------------


def revoquer_delegation(delegation: Delegation, par: Utilisateur, motif: str) -> Delegation:
    """Retire ses pouvoirs au délégataire d'une délégation ACTIVE (``admin.absences``).

    L'absence reste ce qu'elle est (l'absent est toujours absent) ; seule la délégation
    prend fin : ANNULEE si elle n'a pas commencé, sinon ``fin`` est avancée à
    maintenant et elle passe TERMINEE. Une délégation EN_ATTENTE suit son absence :
    on refuse l'absence plutôt que de révoquer. Audit ``delegation.revoquee`` (motif en
    détail) ; le délégataire est notifié comme pour une fin de délégation.
    """
    motif = (motif or "").strip()
    if not motif:
        raise ErreurApi(
            VALIDATION, "Certaines données sont invalides.", details={"motif": ["Obligatoire."]}
        )
    delegation = (
        Delegation.objects.select_for_update(of=("self",))
        .select_related("delegant", "delegataire", "absence")
        .get(pk=delegation.pk)
    )
    if delegation.statut != StatutDelegation.ACTIVE:
        raise _conflit(
            STATUT_INVALIDE,
            "Seule une délégation active peut être révoquée. Une délégation en attente "
            "suit sa demande d'absence : refusez l'absence.",
        )
    if par.pk == delegation.delegant_id or par.pk == delegation.delegataire_id:
        raise ErreurApi(
            PERMISSION_REFUSEE,
            "Vous ne pouvez pas révoquer une délégation qui vous concerne.",
            statut=status.HTTP_403_FORBIDDEN,
        )
    maintenant = timezone.now()
    avant = extraire_champs(delegation, ["statut", "fin", "terminee_le"])
    if maintenant <= delegation.debut:
        delegation.statut = StatutDelegation.ANNULEE
        delegation.save(update_fields=["statut"])
    else:
        delegation.fin = min(delegation.fin, maintenant)
        delegation.statut = StatutDelegation.TERMINEE
        delegation.terminee_le = maintenant
        delegation.save(update_fields=["fin", "statut", "terminee_le"])
    _journaliser_delegation(
        "delegation.revoquee", delegation, avant=avant, acteur=par, detail=motif
    )
    signaux.delegation_terminee.send(sender=Delegation, delegation=delegation)
    return delegation


# --- Entrée en vigueur et clôture (tâches planifiées, § 6.5) --------------------------------------


def activer(delegation: Delegation, maintenant: datetime.datetime, *, acteur: Any = None) -> bool:
    """Date l'entrée en vigueur d'une délégation ACTIVE (une seule fois) ; journalise."""
    if delegation.activee_le is not None or delegation.statut != StatutDelegation.ACTIVE:
        return False
    avant = extraire_champs(delegation, ["activee_le"])
    delegation.activee_le = maintenant
    delegation.save(update_fields=["activee_le"])
    _journaliser_delegation("delegation.active", delegation, avant=avant, acteur=acteur)
    signaux.delegation_active.send(sender=Delegation, delegation=delegation)
    return True


def terminer(delegation: Delegation, maintenant: datetime.datetime, *, acteur: Any = None) -> bool:
    """Passe une délégation ACTIVE à TERMINEE (une seule fois) ; journalise."""
    if delegation.statut != StatutDelegation.ACTIVE:
        return False
    avant = extraire_champs(delegation, ["statut", "terminee_le"])
    delegation.statut = StatutDelegation.TERMINEE
    delegation.terminee_le = maintenant
    delegation.save(update_fields=["statut", "terminee_le"])
    _journaliser_delegation("delegation.terminee", delegation, avant=avant, acteur=acteur)
    signaux.delegation_terminee.send(sender=Delegation, delegation=delegation)
    return True


def _a_traiter(qs):
    # skip_locked : deux passages concurrents (beat en retard) ne traitent pas la même ligne.
    return qs.select_related("delegant", "delegataire").select_for_update(
        skip_locked=True, of=("self",)
    )


def activer_delegations_echues(maintenant: datetime.datetime | None = None) -> int:
    """Délégations ACTIVES dont le début est atteint et pas encore datées. Idempotent."""
    instant = maintenant or timezone.now()
    lignes = _a_traiter(
        Delegation.objects.filter(
            statut=StatutDelegation.ACTIVE,
            activee_le__isnull=True,
            debut__lte=instant,
            fin__gt=instant,
        ).order_by("debut", "id")
    )
    return sum(activer(d, instant) for d in lignes)


def cloturer_delegations_echues(maintenant: datetime.datetime | None = None) -> int:
    """Délégations ACTIVES dont la fin est passée → TERMINEE. Idempotent."""
    instant = maintenant or timezone.now()
    lignes = _a_traiter(
        Delegation.objects.filter(statut=StatutDelegation.ACTIVE, fin__lte=instant).order_by(
            "fin", "id"
        )
    )
    return sum(terminer(d, instant) for d in lignes)
