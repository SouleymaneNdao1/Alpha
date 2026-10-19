"""Raccordement des notifications in-app aux signaux des tâches et des délégations (B9).

Les signaux sont envoyés de façon SYNCHRONE, sous le contexte tenant et DANS la
transaction de l'action (B8) : une notification est validée ou annulée avec elle.

Règles (§ 2.2, § 5.4) :

- ``tache_ouverte`` : le destinataire nommé, ou les titulaires du rôle destinataire
  (dans le périmètre de l'unité, comme la règle de visibilité), hors demandeur ;
- ``tache_reassignee`` : les nouveaux destinataires ;
- ``absence_soumise`` : le délégataire proposé (le valideur est prévenu par sa tâche) ;
- ``absence_decidee`` : le demandeur et, si l'absence est validée, le délégataire
  (§ 5.4) ; si elle est refusée, le délégataire proposé est informé ;
- ``absence_annulee`` : le délégataire ;
- ``delegation_active`` / ``delegation_terminee`` : le délégataire. L'entrée en vigueur
  au moment même de la validation n'est pas notifiée deux fois (déjà dans
  « absence validée »).
"""

from __future__ import annotations

import uuid

from django.dispatch import receiver
from django.utils import timezone

from alpha.delegations import signaux as signaux_delegations
from alpha.delegations.models import StatutAbsence
from alpha.organisation.models import AffectationRole
from alpha.organisation.pouvoirs import parents_des_unites
from alpha.taches import signaux as signaux_taches

from .models import TypeNotification
from .services import notifier

UID = "alpha.notifications"


def _date(instant) -> str:
    return timezone.localtime(instant).strftime("%d/%m/%Y")


def _periode(objet) -> str:
    return f"du {_date(objet.debut)} au {_date(objet.fin)}"


def _unite_et_ancetres(unite_id: uuid.UUID) -> set[uuid.UUID]:
    """L'unité et ses ancêtres (protégé contre un cycle accidentel)."""
    parents = parents_des_unites()
    resultat: set[uuid.UUID] = set()
    courante: uuid.UUID | None = unite_id
    while courante is not None and courante not in resultat:
        resultat.add(courante)
        courante = parents.get(courante)
    return resultat


def destinataires_tache(tache) -> set[uuid.UUID]:
    """Utilisateurs qui voient la tâche en propre (règles 1 et 2 de la visibilité)."""
    if tache.assigne_utilisateur_id is not None:
        return {tache.assigne_utilisateur_id}
    if tache.assigne_role_id is None:
        return set()
    affectations = (
        AffectationRole.objects.en_cours()
        .filter(role_id=tache.assigne_role_id, role__actif=True)
        .values_list("utilisateur_id", "unite_id")
    )
    if tache.assigne_unite_id is None:
        resultat = {u_id for u_id, _ in affectations}
    else:
        # Une affectation couvre l'unité visée si elle porte sur elle, sur un ancêtre ou
        # sur tout l'établissement (sous-arbre de la règle de visibilité).
        couvrantes = _unite_et_ancetres(tache.assigne_unite_id)
        resultat = {
            u_id for u_id, unite_id in affectations if unite_id is None or unite_id in couvrantes
        }
    resultat.discard(tache.demandeur_id)
    return resultat


def _notifier_tache(tache, destinataires) -> None:
    notifier(
        destinataires,
        type=TypeNotification.TACHE_NOUVELLE,
        titre=tache.titre,
        corps=tache.sous_titre,
        lien=tache.lien or "/a-traiter",
    )


@receiver(signaux_taches.tache_ouverte, dispatch_uid=f"{UID}.tache_ouverte")
def tache_ouverte(sender, tache, **kwargs) -> None:
    _notifier_tache(tache, destinataires_tache(tache))


@receiver(signaux_taches.tache_reassignee, dispatch_uid=f"{UID}.tache_reassignee")
def tache_reassignee(sender, tache, avant=None, **kwargs) -> None:
    _notifier_tache(tache, destinataires_tache(tache))


@receiver(signaux_delegations.absence_soumise, dispatch_uid=f"{UID}.absence_soumise")
def absence_soumise(sender, absence, delegation=None, **kwargs) -> None:
    if delegation is None:
        return
    notifier(
        [delegation.delegataire_id],
        type=TypeNotification.DELEGATION_PROPOSEE,
        titre=f"{absence.utilisateur.nom_complet} vous propose comme délégataire",
        corps=f"Absence {_periode(absence)}, en attente de validation.",
        lien="/mon-compte?onglet=absences",
    )


@receiver(signaux_delegations.absence_decidee, dispatch_uid=f"{UID}.absence_decidee")
def absence_decidee(sender, absence, delegation=None, **kwargs) -> None:
    demandeur = absence.utilisateur
    if absence.statut == StatutAbsence.VALIDEE:
        notifier(
            [demandeur],
            type=TypeNotification.ABSENCE_VALIDEE,
            titre="Votre absence est validée",
            corps=f"Absence {_periode(absence)}"
            + (f" · délégataire {delegation.delegataire.nom_complet}." if delegation else "."),
            lien="/mon-compte?onglet=absences",
        )
        if delegation is not None:
            en_vigueur = delegation.activee_le is not None
            notifier(
                [delegation.delegataire_id],
                type=TypeNotification.DELEGATION_RECUE,
                titre=f"Délégation de {demandeur.nom_complet}",
                corps=f"Vous traitez ses tâches {_periode(delegation)}"
                + (" (en vigueur)." if en_vigueur else "."),
                lien="/a-traiter",
            )
        return
    if absence.statut == StatutAbsence.REFUSEE:
        motif = f" Motif : {absence.motif_refus}" if absence.motif_refus else ""
        notifier(
            [demandeur],
            type=TypeNotification.ABSENCE_REFUSEE,
            titre="Votre absence est refusée",
            corps=f"Absence {_periode(absence)}.{motif}",
            lien="/mon-compte?onglet=absences",
        )
        if delegation is not None:
            notifier(
                [delegation.delegataire_id],
                type=TypeNotification.DELEGATION_ANNULEE,
                titre=f"Délégation de {demandeur.nom_complet} non retenue",
                corps=f"L'absence {_periode(absence)} a été refusée.",
                lien="/a-traiter",
            )


@receiver(signaux_delegations.absence_annulee, dispatch_uid=f"{UID}.absence_annulee")
def absence_annulee(sender, absence, delegation=None, **kwargs) -> None:
    if delegation is None:
        return
    notifier(
        [delegation.delegataire_id],
        type=TypeNotification.DELEGATION_ANNULEE,
        titre=f"Absence de {absence.utilisateur.nom_complet} annulée",
        corps=f"La délégation {_periode(delegation)} est annulée ou écourtée.",
        lien="/a-traiter",
    )


@receiver(signaux_delegations.delegation_active, dispatch_uid=f"{UID}.delegation_active")
def delegation_active(sender, delegation, **kwargs) -> None:
    absence = delegation.absence
    if (
        absence is not None
        and absence.decide_le is not None
        and absence.decide_le == delegation.activee_le
    ):
        return  # entrée en vigueur à la validation : déjà dit dans « délégation reçue »
    notifier(
        [delegation.delegataire_id],
        type=TypeNotification.DELEGATION_ACTIVE,
        titre=f"Délégation de {delegation.delegant.nom_complet} en vigueur",
        corps=f"Vous traitez ses tâches {_periode(delegation)}.",
        lien="/a-traiter",
    )


@receiver(signaux_delegations.delegation_terminee, dispatch_uid=f"{UID}.delegation_terminee")
def delegation_terminee(sender, delegation, **kwargs) -> None:
    notifier(
        [delegation.delegataire_id],
        type=TypeNotification.DELEGATION_TERMINEE,
        titre=f"Délégation de {delegation.delegant.nom_complet} terminée",
        corps="Ses tâches ne figurent plus dans votre liste « À traiter ».",
        lien="/a-traiter",
    )
