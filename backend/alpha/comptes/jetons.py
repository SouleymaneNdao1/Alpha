"""Émission des jetons à usage unique (§ 2.2 ``jeton_usage_unique``, § 4.3, § 4.5, § 4.7).

Le jeton en clair (32 octets, base64url) n'est renvoyé qu'à l'appelant, qui le met
dans l'e-mail ; seule son empreinte SHA-256 est enregistrée. Émettre un jeton annule
les jetons en cours du même objet. Durées (décision P2) : invitation et
réinitialisation selon ``ParametresEtablissement`` ; réenrôlement 24 h (§ 4.5).
L'invitation est émise par l'administration (B7, ``administration._emettre_invitation``).
"""

from __future__ import annotations

import datetime
import secrets

from django.utils import timezone

from alpha.tenancy.models import ParametresEtablissement

from .models import JetonUsageUnique, ObjetJeton, Utilisateur
from .resolution import empreinte_jeton

VALIDITE_REINIT_MDP_MIN_DEFAUT = 30
VALIDITE_REENROLEMENT = datetime.timedelta(hours=24)


def annuler_en_cours(utilisateur: Utilisateur, objets: list[str] | None = None) -> int:
    qs = JetonUsageUnique.objects.filter(
        utilisateur_id=utilisateur.pk, utilise_le__isnull=True, annule_le__isnull=True
    )
    if objets is not None:
        qs = qs.filter(objet__in=objets)
    return qs.update(annule_le=timezone.now())


def emettre(
    utilisateur: Utilisateur,
    objet: str,
    validite: datetime.timedelta,
    *,
    par: Utilisateur | None = None,
) -> tuple[JetonUsageUnique, str]:
    """Nouveau jeton ``objet`` (les précédents du même objet sont annulés) ; (ligne, clair)."""
    annuler_en_cours(utilisateur, [objet])
    clair = secrets.token_urlsafe(32)
    jeton = JetonUsageUnique.objects.create(
        utilisateur=utilisateur,
        etablissement_id=utilisateur.etablissement_id,
        objet=objet,
        jeton_hash=empreinte_jeton(clair),
        expire_le=timezone.now() + validite,
        cree_par=par,
    )
    return jeton, clair


def validite_reinit_mdp(utilisateur: Utilisateur) -> datetime.timedelta:
    minutes = VALIDITE_REINIT_MDP_MIN_DEFAUT
    if utilisateur.etablissement_id:
        parametres = ParametresEtablissement.objects.filter(
            etablissement_id=utilisateur.etablissement_id
        ).first()
        if parametres is not None:
            minutes = parametres.validite_reinit_mdp_min
    return datetime.timedelta(minutes=minutes)


def emettre_reinit_mdp(utilisateur: Utilisateur) -> tuple[JetonUsageUnique, str]:
    return emettre(utilisateur, ObjetJeton.REINIT_MDP, validite_reinit_mdp(utilisateur))


def emettre_reenrolement(
    utilisateur: Utilisateur, *, par: Utilisateur | None = None
) -> tuple[JetonUsageUnique, str]:
    return emettre(utilisateur, ObjetJeton.REENROLEMENT_MFA, VALIDITE_REENROLEMENT, par=par)
