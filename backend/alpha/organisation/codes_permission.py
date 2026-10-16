"""Codes de permission système, stockés dans ``role.permissions`` (architecture § 2.3).

Ce module est la SEULE source des codes valides : la contrainte ``CHECK`` de la
table ``role`` (``permissions <@ ARRAY[...]``) est générée à partir de
``CodePermission.values``. Ajouter un code (S2 : circuits, dossiers…) impose
donc une migration, ce qui est voulu.

Les permissions DRF ``Perm(x)`` (B5 à B11) et le menu du frontend
(``Moi.permissions``) utilisent ces mêmes chaînes.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import models


class CodePermission(models.TextChoices):
    ADMIN_UTILISATEURS = (
        "admin.utilisateurs",
        "Inviter, modifier, suspendre, déverrouiller les utilisateurs ; "
        "traiter « téléphone perdu »",
    )
    ADMIN_ROLES = "admin.roles", "Gérer le catalogue des rôles et les habilitations"
    ADMIN_ORGANISATION = "admin.organisation", "Gérer les unités et périmètres"
    ADMIN_SECURITE = "admin.securite", "Régler les paramètres de sécurité de l'établissement"
    ADMIN_ABSENCES = "admin.absences", "Voir et valider toute absence (à défaut de responsable)"
    AUDIT_LECTURE = "audit.lecture", "Consulter le journal d'audit"
    AUDIT_EXPORT = "audit.export", "Exporter le journal d'audit (Excel)"


#: Tous les codes ``admin.*`` (rôle système « Administrateur ALPHA »).
PERMISSIONS_ADMIN: tuple[str, ...] = tuple(
    c for c in CodePermission.values if c.startswith("admin.")
)
#: Tous les codes ``audit.*`` (rôle « Auditeur interne »).
PERMISSIONS_AUDIT: tuple[str, ...] = tuple(
    c for c in CodePermission.values if c.startswith("audit.")
)
#: Permission dont au moins un utilisateur ACTIF doit rester titulaire (invariant, B7).
PERMISSION_DERNIER_ADMIN = CodePermission.ADMIN_UTILISATEURS.value


def codes_inconnus(codes: Iterable[str]) -> list[str]:
    """Codes absents du catalogue (liste triée, vide si tout est valide)."""
    return sorted(set(codes) - set(CodePermission.values))


def valider_codes(codes: Iterable[str]) -> None:
    """Lève ``ValidationError`` si un code n'existe pas (utilisable comme validateur de champ)."""
    inconnus = codes_inconnus(codes)
    if inconnus:
        raise ValidationError(
            "Code(s) de permission inconnu(s) : %(codes)s.",
            code="permission_inconnue",
            params={"codes": ", ".join(inconnus)},
        )
