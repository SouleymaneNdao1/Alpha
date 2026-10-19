"""Visibilité des tâches et regroupement par urgence (architecture § 2.2, tâche B8).

**Visibilité** (``visibles_pour(utilisateur)``) : tâche OUVERTE et
1. ``assigne_utilisateur = u`` ; ou
2. ``assigne_role`` parmi les rôles actifs de ``u`` (affectations en cours) et
   ``assigne_unite`` vide ou dans le sous-arbre d'une unité d'affectation de ``u``
   pour ce rôle (une affectation sur tout l'établissement couvre toute unité) ; ou
3. règles 1 ou 2 appliquées à chaque délégant ``d`` ayant une délégation
   EFFECTIVE vers ``u`` (``ACTIVE`` et ``debut <= now < fin``), limitée au rôle
   délégué s'il est renseigné.

Pas de sous-délégation : la règle 3 n'est appliquée qu'une fois (les tâches que
``d`` voit lui-même par délégation ne passent pas à ``u``). La visibilité est
calculée à l'instant de la requête : la fin de la délégation la retire aussitôt,
sans attendre la tâche planifiée de clôture.

Chaque tâche du queryset porte ``par_delegation_de_id`` : NULL si ``u`` la voit
en propre, sinon l'identifiant du délégant (« par délégation de … »).

**Urgence** (``annoter_urgence``), dans le fuseau de l'établissement (Africa/Dakar
par défaut) : ``EN_RETARD`` (échéance passée), ``AUJOURDHUI`` (même date locale),
``CETTE_SEMAINE`` (jusqu'au dimanche 23:59:59 local), ``PLUS_TARD`` (au-delà, ou
sans échéance). Tri : groupe, échéance croissante, création.
"""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Case, F, IntegerField, Q, QuerySet, UUIDField, Value, When
from django.utils import timezone

from alpha.core import contexte
from alpha.delegations.models import Delegation, StatutDelegation
from alpha.organisation.models import AffectationRole
from alpha.organisation.pouvoirs import parents_des_unites
from alpha.tenancy.models import Etablissement

from .models import Groupe, StatutTache, Tache

#: Ordre d'affichage des groupes (valeur de l'annotation ``groupe_ordre``).
ORDRE_GROUPES: tuple[str, ...] = (
    Groupe.EN_RETARD,
    Groupe.AUJOURDHUI,
    Groupe.CETTE_SEMAINE,
    Groupe.PLUS_TARD,
)
_AUCUNE = Q(pk__in=[])


# --- Délégations effectives -------------------------------------------------------------------


@dataclass(frozen=True)
class DelegationRecue:
    delegation_id: uuid.UUID
    delegant_id: uuid.UUID
    delegant_nom: str
    role_id: uuid.UUID | None


def delegations_effectives_vers(
    utilisateur_id: uuid.UUID, maintenant: datetime.datetime | None = None
) -> list[DelegationRecue]:
    """Délégations effectives dont ``utilisateur_id`` est le délégataire, à l'instant donné."""
    instant = maintenant or timezone.now()
    lignes = (
        Delegation.objects.filter(
            delegataire_id=utilisateur_id,
            statut=StatutDelegation.ACTIVE,
            debut__lte=instant,
            fin__gt=instant,
        )
        .order_by("debut", "id")
        .values_list("id", "delegant_id", "delegant__prenom", "delegant__nom", "role_id")
    )
    return [
        DelegationRecue(d_id, delegant, f"{prenom} {nom}".strip(), role)
        for d_id, delegant, prenom, nom, role in lignes
    ]


def delegants_effectifs(
    utilisateur_id: uuid.UUID,
    maintenant: datetime.datetime | None = None,
    *,
    tous_roles_seulement: bool = False,
) -> set[uuid.UUID]:
    """Délégants pour lesquels ``utilisateur_id`` agit en ce moment.

    ``tous_roles_seulement`` : ne retient que les délégations sans limite de rôle
    (pouvoirs propres à la personne, ex. valider l'absence d'un collaborateur).
    """
    return {
        d.delegant_id
        for d in delegations_effectives_vers(utilisateur_id, maintenant)
        if not (tous_roles_seulement and d.role_id is not None)
    }


# --- Conditions de visibilité -------------------------------------------------------------------


def _enfants(parents: Mapping[uuid.UUID, uuid.UUID | None]) -> dict[uuid.UUID, list[uuid.UUID]]:
    enfants: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for unite, parent in parents.items():
        if parent is not None:
            enfants[parent].append(unite)
    return enfants


def sous_arbre(unite_id: uuid.UUID, enfants: Mapping[uuid.UUID, list[uuid.UUID]]) -> set[uuid.UUID]:
    """L'unité et toutes ses descendantes (protégé contre un cycle accidentel)."""
    vues: set[uuid.UUID] = set()
    a_voir = [unite_id]
    while a_voir:
        courante = a_voir.pop()
        if courante in vues:
            continue
        vues.add(courante)
        a_voir.extend(enfants.get(courante, ()))
    return vues


def _habilitations(utilisateurs: Iterable[uuid.UUID]) -> dict[uuid.UUID, set]:
    """{utilisateur: {(role_id, unite_id)}} des affectations en cours sur des rôles actifs."""
    resultat: dict[uuid.UUID, set] = defaultdict(set)
    for u_id, r_id, unite_id in (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id__in=list(utilisateurs), role__actif=True)
        .values_list("utilisateur_id", "role_id", "unite_id")
    ):
        resultat[u_id].add((r_id, unite_id))
    return resultat


def _condition(
    utilisateur_id: uuid.UUID,
    habilitations: set,
    enfants: Mapping[uuid.UUID, list[uuid.UUID]],
    *,
    role_id: uuid.UUID | None = None,
) -> Q:
    """Règles 1 et 2 pour un utilisateur ; ``role_id`` : restreint au rôle délégué."""
    if role_id is None:
        condition = Q(assigne_utilisateur_id=utilisateur_id)
    else:
        condition = Q(assigne_utilisateur_id=utilisateur_id, assigne_role_id=role_id)
    for r_id, unite_id in habilitations:
        if role_id is not None and r_id != role_id:
            continue
        if unite_id is None:
            condition |= Q(assigne_role_id=r_id)
        else:
            condition |= Q(assigne_role_id=r_id) & (
                Q(assigne_unite_id__isnull=True)
                | Q(assigne_unite_id__in=sorted(sous_arbre(unite_id, enfants)))
            )
    return condition


def visibles_pour(utilisateur, maintenant: datetime.datetime | None = None) -> QuerySet[Tache]:
    """Tâches ouvertes visibles par ``utilisateur`` (instance ou identifiant), annotées.

    Annotation : ``par_delegation_de_id`` (uuid du délégant, ou NULL).
    """
    u_id = getattr(utilisateur, "pk", utilisateur)
    instant = maintenant or timezone.now()
    recues = delegations_effectives_vers(u_id, instant)
    habilitations = _habilitations({u_id, *(d.delegant_id for d in recues)})
    enfants = _enfants(parents_des_unites())

    directe = _condition(u_id, habilitations.get(u_id, set()), enfants)
    branches = [When(directe, then=Value(None))]
    visible = directe
    for recue in recues:
        condition = _condition(
            recue.delegant_id,
            habilitations.get(recue.delegant_id, set()),
            enfants,
            role_id=recue.role_id,
        )
        branches.append(When(condition, then=Value(recue.delegant_id)))
        visible |= condition

    return (
        Tache.objects.filter(statut=StatutTache.OUVERTE)
        .filter(visible)
        .annotate(
            par_delegation_de_id=Case(*branches, default=Value(None), output_field=UUIDField())
        )
    )


# --- Urgence ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bornes:
    """Instants qui séparent les groupes, calculés dans le fuseau de l'établissement."""

    maintenant: datetime.datetime
    demain: datetime.datetime  # 00:00 local du lendemain
    lundi_prochain: datetime.datetime  # 00:00 local du lundi suivant
    fuseau: datetime.tzinfo

    def groupe_de(self, echeance: datetime.datetime | None) -> str:
        if echeance is None:
            return Groupe.PLUS_TARD
        if echeance < self.maintenant:
            return Groupe.EN_RETARD
        if echeance < self.demain:
            return Groupe.AUJOURDHUI
        if echeance < self.lundi_prochain:
            return Groupe.CETTE_SEMAINE
        return Groupe.PLUS_TARD

    def retard_jours(self, echeance: datetime.datetime | None) -> int | None:
        """Jours calendaires (locaux) de retard ; ``None`` si la tâche n'est pas en retard."""
        if echeance is None or echeance >= self.maintenant:
            return None
        aujourd_hui = self.maintenant.astimezone(self.fuseau).date()
        return (aujourd_hui - echeance.astimezone(self.fuseau).date()).days


def fuseau_courant() -> datetime.tzinfo:
    """Fuseau de l'établissement courant (``Africa/Dakar`` par défaut)."""
    nom = None
    tenant = contexte.tenant_courant()
    if tenant is not None:
        nom = (
            Etablissement.objects.filter(id=tenant).values_list("fuseau_horaire", flat=True).first()
        )
    try:
        return zoneinfo.ZoneInfo(nom or settings.TIME_ZONE)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def bornes_urgence(
    maintenant: datetime.datetime | None = None, fuseau: datetime.tzinfo | None = None
) -> Bornes:
    instant = maintenant or timezone.now()
    tz = fuseau or fuseau_courant()
    jour = instant.astimezone(tz).date()
    demain = datetime.datetime.combine(jour + datetime.timedelta(days=1), datetime.time(), tz)
    # weekday() : lundi = 0 ; le lundi suivant est à 7 - weekday jours.
    lundi = datetime.datetime.combine(
        jour + datetime.timedelta(days=7 - jour.weekday()), datetime.time(), tz
    )
    return Bornes(instant, demain, lundi, tz)


def annoter_urgence(qs: QuerySet[Tache], bornes: Bornes) -> QuerySet[Tache]:
    """Ajoute ``groupe_ordre`` (0 à 3, ``ORDRE_GROUPES``) ; tri : groupe, échéance, création."""
    return qs.annotate(
        groupe_ordre=Case(
            When(echeance__isnull=True, then=Value(3)),
            When(echeance__lt=bornes.maintenant, then=Value(0)),
            When(echeance__lt=bornes.demain, then=Value(1)),
            When(echeance__lt=bornes.lundi_prochain, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by("groupe_ordre", F("echeance").asc(nulls_last=True), "cree_le", "id")
