"""Utilitaires de test des comptes et de l'organisation (tâche B3).

Les créations passent par la connexion ``default`` (alpha_owner) sous le
contexte de l'établissement visé, comme le ferait le provisionnement.
"""

from __future__ import annotations

import datetime
import secrets

from django.utils import timezone

from alpha.comptes.models import JetonUsageUnique, ObjetJeton, StatutUtilisateur, Utilisateur
from alpha.comptes.resolution import empreinte_jeton
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement


def creer_utilisateur(etablissement: Etablissement, email: str, **champs) -> Utilisateur:
    champs.setdefault("prenom", "Awa")
    champs.setdefault("nom", "Diop")
    champs.setdefault("statut", StatutUtilisateur.ACTIF)
    with contexte_tenant(etablissement.id):
        return Utilisateur.objects.create_user(email=email, **champs)


def creer_super_admin(email: str = "admin@fyxop.test") -> Utilisateur:
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
        return Utilisateur.objects.create_user(
            email=email, prenom="Admin", nom="FYXOP", est_super_admin=True, statut="ACTIF"
        )


def creer_jeton(
    utilisateur: Utilisateur,
    *,
    objet: str = ObjetJeton.INVITATION,
    expire_dans: datetime.timedelta = datetime.timedelta(hours=72),
    **champs,
) -> tuple[str, JetonUsageUnique]:
    """Crée un jeton ; renvoie (jeton en clair, ligne)."""
    clair = secrets.token_urlsafe(32)
    if utilisateur.est_super_admin:
        cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=utilisateur.id)
    else:
        cm = contexte_tenant(utilisateur.etablissement_id)
    with cm:
        jeton = JetonUsageUnique.objects.create(
            utilisateur=utilisateur,
            objet=objet,
            jeton_hash=empreinte_jeton(clair),
            expire_le=timezone.now() + expire_dans,
            **champs,
        )
    return clair, jeton
