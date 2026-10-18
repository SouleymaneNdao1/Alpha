"""Comparaison des pouvoirs de deux utilisateurs (décision P5 du 15/10/2026).

« Le délégataire doit détenir des pouvoirs au moins égaux à ceux de l'absent. »
Ce module fournit de quoi le vérifier ; la vérification elle-même est faite par
la tâche B8 (création de la délégation).

Au S1, les pouvoirs d'un utilisateur sont :
- ses habilitations en vigueur : couples (rôle actif, unité) de ses affectations
  en cours (``AffectationRole.objects.en_cours()``, fin NULL),
  l'unité ``None`` signifiant « tout l'établissement » ;
- l'union des codes de permission système de ces rôles.

A « couvre » B si A a toutes les permissions de B et, pour chaque habilitation
(rôle, unité) de B, détient le même rôle sur la même unité, sur une unité
ancêtre, ou sur tout l'établissement.

S2/S3 (non implémenté) : plafonds de montant et types de dossier (``delegation.portee``,
barème des délégations) compléteront cette comparaison.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from .models import AffectationRole, UniteOrganisationnelle

Habilitation = tuple[uuid.UUID, uuid.UUID | None]  # (role_id, unite_id)


@dataclass(frozen=True)
class Pouvoirs:
    habilitations: frozenset[Habilitation]
    permissions: frozenset[str]

    @classmethod
    def de(
        cls,
        utilisateur_id: uuid.UUID,
        *,
        a_la_date: datetime.date | None = None,
        role_id: uuid.UUID | None = None,
    ) -> Pouvoirs:
        """Pouvoirs en vigueur de l'utilisateur (établissement courant).

        ``role_id`` : limite au rôle donné (délégation limitée à un rôle, § 2.2).
        """
        # Affectations EN COURS (fin NULL) : même définition que les permissions de
        # l'API (B7, ``permissions.permissions_de``) ; une affectation terminée le jour
        # même ne compte plus (ajout B8).
        affectations = AffectationRole.objects.en_cours(a_la_date).filter(
            utilisateur_id=utilisateur_id, role__actif=True
        )
        if role_id is not None:
            affectations = affectations.filter(role_id=role_id)
        habilitations: set[Habilitation] = set()
        permissions: set[str] = set()
        for r_id, u_id, perms in affectations.values_list(
            "role_id", "unite_id", "role__permissions"
        ):
            habilitations.add((r_id, u_id))
            permissions.update(perms or ())
        return cls(frozenset(habilitations), frozenset(permissions))

    def couvre(self, autre: Pouvoirs, parents: Mapping[uuid.UUID, uuid.UUID | None]) -> bool:
        """Vrai si ces pouvoirs sont au moins égaux à ``autre``.

        ``parents`` : {unite_id: parent_id} de l'établissement (``parents_des_unites()``).
        """
        if not self.permissions >= autre.permissions:
            return False
        return all(self._detient(role, unite, parents) for role, unite in autre.habilitations)

    def _detient(
        self,
        role: uuid.UUID,
        unite: uuid.UUID | None,
        parents: Mapping[uuid.UUID, uuid.UUID | None],
    ) -> bool:
        if (role, None) in self.habilitations:
            return True  # le rôle sur tout l'établissement couvre toute unité
        vues: set[uuid.UUID] = set()
        courante = unite
        while courante is not None and courante not in vues:
            if (role, courante) in self.habilitations:
                return True
            vues.add(courante)
            courante = parents.get(courante)
        return False


def parents_des_unites() -> dict[uuid.UUID, uuid.UUID | None]:
    """Arbre des unités de l'établissement courant : {unite_id: parent_id}."""
    return dict(UniteOrganisationnelle.objects.values_list("id", "parent_id"))
