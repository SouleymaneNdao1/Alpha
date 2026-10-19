"""Politique de mot de passe (architecture § 4.9, décision P3) et historique.

Validateurs déclarés dans ``AUTH_PASSWORD_VALIDATORS`` (en plus de ceux de Django) :

- ``LongueurEtablissementValidator`` : ``mdp_longueur_min`` de l'établissement (≥ 12) ;
- ``CategoriesValidator`` : au moins 3 catégories sur 4 (minuscule, majuscule, chiffre, symbole) ;
- ``AnneeNaissanceValidator`` : refus des suites « 19xx » / « 20xx » ;
- ``HistoriqueValidator`` : différent des ``mdp_historique`` derniers mots de passe.

``definir_mot_de_passe(utilisateur, mot_de_passe)`` valide, hache (Argon2id),
alimente ``historique_mot_de_passe`` et met à jour ``mdp_modifie_le`` (utilisé
par l'activation, la réinitialisation et « Mon compte », B6/B9).
"""

from __future__ import annotations

import re

from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import HistoriqueMotDePasse, Utilisateur

LONGUEUR_MIN_PLATEFORME = 12
HISTORIQUE_PLATEFORME = 5


def _parametres(utilisateur: Utilisateur | None):
    if utilisateur is None or utilisateur.est_super_admin or not utilisateur.etablissement_id:
        return None
    from alpha.tenancy.models import ParametresEtablissement

    return ParametresEtablissement.objects.filter(
        etablissement_id=utilisateur.etablissement_id
    ).first()


class LongueurEtablissementValidator:
    def validate(self, password: str, user=None) -> None:
        parametres = _parametres(user)
        minimum = parametres.mdp_longueur_min if parametres else LONGUEUR_MIN_PLATEFORME
        if len(password) < minimum:
            raise ValidationError(
                f"Le mot de passe doit comporter au moins {minimum} caractères.",
                code="mdp_trop_court",
            )

    def get_help_text(self) -> str:
        return "12 caractères minimum (ou davantage selon votre établissement)."


class CategoriesValidator:
    def validate(self, password: str, user=None) -> None:
        categories = sum(
            (
                bool(re.search(r"[a-zà-ÿ]", password)),
                bool(re.search(r"[A-ZÀ-Þ]", password)),
                bool(re.search(r"\d", password)),
                bool(re.search(r"[^\w\s]|_", password)),
            )
        )
        if categories < 3:
            raise ValidationError(
                "Utilisez au moins 3 types de caractères parmi : minuscules, majuscules, "
                "chiffres et symboles.",
                code="mdp_categories",
            )

    def get_help_text(self) -> str:
        return "Au moins 3 catégories sur 4 : minuscule, majuscule, chiffre, symbole."


class AnneeNaissanceValidator:
    _ANNEE = re.compile(r"(19|20)\d\d")

    def validate(self, password: str, user=None) -> None:
        if self._ANNEE.search(password):
            raise ValidationError(
                "Évitez les années (19xx, 20xx), comme une date de naissance.",
                code="mdp_annee",
            )

    def get_help_text(self) -> str:
        return "Évitez votre date de naissance."


class HistoriqueValidator:
    def validate(self, password: str, user=None) -> None:
        if user is None or user.pk is None:
            return
        parametres = _parametres(user)
        nombre = parametres.mdp_historique if parametres else HISTORIQUE_PLATEFORME
        if nombre <= 0:
            return
        anciens = list(
            HistoriqueMotDePasse.objects.filter(utilisateur_id=user.pk)
            .order_by("-cree_le")
            .values_list("password", flat=True)[:nombre]
        )
        if any(check_password(password, ancien) for ancien in anciens):
            raise ValidationError(
                f"Ce mot de passe a déjà été utilisé (les {nombre} derniers sont interdits).",
                code="mdp_historique",
            )

    def get_help_text(self) -> str:
        return "Différent de vos 5 derniers mots de passe."


def definir_mot_de_passe(utilisateur: Utilisateur, mot_de_passe: str) -> None:
    """Valide (lève ``ValidationError``), enregistre et historise le nouveau mot de passe."""
    validate_password(mot_de_passe, user=utilisateur)
    utilisateur.set_password(mot_de_passe)
    utilisateur.mdp_modifie_le = timezone.now()
    utilisateur.save(update_fields=["password", "mdp_modifie_le", "modifie_le"])
    HistoriqueMotDePasse.objects.create(
        utilisateur=utilisateur,
        etablissement_id=utilisateur.etablissement_id,
        password=utilisateur.password,
    )
    parametres = _parametres(utilisateur)
    garder = max(parametres.mdp_historique if parametres else HISTORIQUE_PLATEFORME, 1)
    anciens = HistoriqueMotDePasse.objects.filter(utilisateur_id=utilisateur.pk).order_by(
        "-cree_le", "-id"
    )
    a_supprimer = list(anciens.values_list("id", flat=True)[garder:])
    if a_supprimer:
        HistoriqueMotDePasse.objects.filter(id__in=a_supprimer).delete()
