"""Services d'administration de l'organisation : catalogue des rôles, unités, invariant (B7).

Toutes les fonctions s'exécutent sous le contexte tenant de l'établissement (vue
d'administration) ; chaque écriture est journalisée (§ 6.1) avec ``avant``/``apres``
restreints à la liste blanche ``AUDIT_CHAMPS`` du modèle.

Invariant « dernier administrateur » (§ 2.3) : il reste toujours au moins un
utilisateur ``ACTIF`` titulaire de ``admin.utilisateurs`` (affectation en cours sur
un rôle actif). ``preserver_dernier_administrateur()`` encadre toute opération qui
peut retirer ce droit (suspension, fin d'affectation, désactivation ou modification
d'un rôle) : verrou par établissement, opération, contrôle, et annulation de
l'opération (409 ``DERNIER_ADMINISTRATEUR``) si elle retirait le dernier titulaire.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db import IntegrityError, connection, transaction
from django.db.models.functions import Lower

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.comptes.models import StatutUtilisateur
from alpha.core import contexte
from alpha.core.erreurs import ErreurApi

from .codes_permission import PERMISSION_DERNIER_ADMIN
from .models import AffectationRole, Role, UniteOrganisationnelle

DERNIER_ADMINISTRATEUR = "DERNIER_ADMINISTRATEUR"
ROLE_SYSTEME = "ROLE_SYSTEME"
LIBELLE_EXISTE = "LIBELLE_EXISTE"
CODE_EXISTE = "CODE_EXISTE"


# --- Invariant « dernier administrateur » -------------------------------------------------


def titulaires_administration() -> set[uuid.UUID]:
    """Utilisateurs ACTIFS titulaires de ``admin.utilisateurs`` (établissement courant)."""
    return set(
        AffectationRole.objects.en_cours()
        .filter(
            role__actif=True,
            role__permissions__contains=[PERMISSION_DERNIER_ADMIN],
            utilisateur__statut=StatutUtilisateur.ACTIF,
        )
        .values_list("utilisateur_id", flat=True)
    )


def verrouiller_etablissement() -> None:
    """Verrou transactionnel par établissement : sérialise les opérations sur l'invariant.

    Sans lui, deux administrateurs qui se suspendent mutuellement au même instant
    passeraient chacun le contrôle. Verrou consultatif (``pg_advisory_xact_lock``),
    libéré à la fin de la transaction ; aucun droit particulier requis.
    """
    tenant = contexte.tenant_courant()
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"alpha-admin:{tenant}"]
        )


@contextmanager
def preserver_dernier_administrateur() -> Iterator[None]:
    """Exécute le bloc, puis l'annule (409) s'il a retiré le dernier administrateur actif.

    Si l'établissement n'avait déjà aucun administrateur actif, le bloc n'est pas
    refusé (rien n'est retiré) : la remédiation relève du super-admin (P4).
    """
    verrouiller_etablissement()
    avant = titulaires_administration()
    with transaction.atomic():
        yield
        if avant and not titulaires_administration():
            raise ErreurApi(
                DERNIER_ADMINISTRATEUR,
                "Opération impossible : il doit rester au moins un administrateur actif "
                "(titulaire de la permission « admin.utilisateurs ») dans l'établissement.",
                statut=409,
            )


# --- Catalogue des rôles ----------------------------------------------------------------------


def _slug(texte: str) -> str:
    """Code de rôle dérivé du libellé : « Analyste crédit » → « analyste-credit »."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")
    return slug[:50].strip("-") or "role"


def _verifier_libelle_libre(libelle: str, *, sauf: uuid.UUID | None = None) -> None:
    qs = Role.objects.annotate(l=Lower("libelle")).filter(l=libelle.lower())
    if sauf is not None:
        qs = qs.exclude(id=sauf)
    if qs.exists():
        raise ErreurApi(
            LIBELLE_EXISTE, "Un rôle porte déjà ce libellé dans le catalogue.", statut=409
        )


def creer_role(*, par: Any, libelle: str, code: str | None = None, **champs: Any) -> Role:
    """Ajoute un rôle au catalogue (``role.cree``)."""
    libelle = libelle.strip()
    _verifier_libelle_libre(libelle)
    code = code or _slug(libelle)
    if Role.objects.filter(code=code).exists():
        raise ErreurApi(CODE_EXISTE, "Un rôle porte déjà ce code dans le catalogue.", statut=409)
    role = Role(libelle=libelle, code=code, est_systeme=False, actif=True, **champs)
    try:
        with transaction.atomic():
            role.save()
    except IntegrityError:  # course entre deux créations simultanées
        raise ErreurApi(
            LIBELLE_EXISTE, "Un rôle porte déjà ce libellé ou ce code.", statut=409
        ) from None
    journaliser(
        "role.cree", Categorie.PARAMETRAGE, objet=role, apres=extraire_champs(role), acteur=par
    )
    return role


def modifier_role(role: Role, *, par: Any, **champs: Any) -> Role:
    """Modifie libellé, description, permissions ou ordre (``role.modifie``).

    Rôle système : ses permissions ne peuvent pas être retirées (409 ``ROLE_SYSTEME``) ;
    en ajouter reste possible. Retirer ``admin.utilisateurs`` d'un rôle est soumis à
    l'invariant du dernier administrateur.
    """
    if "libelle" in champs:
        champs["libelle"] = champs["libelle"].strip()
        _verifier_libelle_libre(champs["libelle"], sauf=role.id)
    if "permissions" in champs:
        champs["permissions"] = sorted(set(champs["permissions"]))
        if role.est_systeme and not set(role.permissions) <= set(champs["permissions"]):
            raise ErreurApi(
                ROLE_SYSTEME,
                "Les permissions d'un rôle système ne peuvent pas être retirées.",
                statut=409,
            )
    modifies = [c for c, v in champs.items() if getattr(role, c) != v]
    if not modifies:
        return role
    avant = extraire_champs(role, modifies)
    with preserver_dernier_administrateur():
        for cle, valeur in champs.items():
            setattr(role, cle, valeur)
        try:
            with transaction.atomic():
                role.save()
        except IntegrityError:
            raise ErreurApi(LIBELLE_EXISTE, "Un rôle porte déjà ce libellé.", statut=409) from None
    journaliser(
        "role.modifie",
        Categorie.PARAMETRAGE,
        objet=role,
        avant=avant,
        apres=extraire_champs(role, modifies),
        acteur=par,
    )
    return role


def changer_activation_role(role: Role, *, par: Any, actif: bool) -> Role:
    """Active ou désactive un rôle (``role.active`` / ``role.desactive``).

    Un rôle système ne change pas d'état (409 ``ROLE_SYSTEME``). La désactivation est
    soumise à l'invariant du dernier administrateur. Les affectations existantes sont
    conservées (elles n'ouvrent plus de droits tant que le rôle est inactif).
    """
    if role.est_systeme:
        raise ErreurApi(
            ROLE_SYSTEME,
            "Le rôle système « Administrateur ALPHA » reste toujours actif.",
            statut=409,
        )
    if role.actif == actif:
        return role
    avant = extraire_champs(role, ["actif"])
    with preserver_dernier_administrateur():
        role.actif = actif
        role.save(update_fields=["actif", "modifie_le"])
    journaliser(
        "role.active" if actif else "role.desactive",
        Categorie.PARAMETRAGE,
        objet=role,
        avant=avant,
        apres=extraire_champs(role, ["actif"]),
        acteur=par,
    )
    return role


# --- Unités organisationnelles ------------------------------------------------------------------


def _verifier_parent(unite_id: uuid.UUID | None, parent: UniteOrganisationnelle | None) -> None:
    """Refuse un parent qui créerait un cycle (l'unité elle-même ou l'un de ses descendants)."""
    if parent is None or unite_id is None:
        return
    parents = dict(UniteOrganisationnelle.objects.values_list("id", "parent_id"))
    courant: uuid.UUID | None = parent.id
    vus: set[uuid.UUID] = set()
    while courant is not None and courant not in vus:
        if courant == unite_id:
            raise ErreurApi(
                "VALIDATION",
                "Certaines données sont invalides.",
                details={
                    "parent_id": [
                        "Une unité ne peut pas être rattachée à elle-même "
                        "ni à l'une de ses sous-unités."
                    ]
                },
            )
        vus.add(courant)
        courant = parents.get(courant)


def _enregistrer_unite(unite: UniteOrganisationnelle) -> None:
    try:
        with transaction.atomic():
            unite.save()
    except IntegrityError:
        raise ErreurApi(
            CODE_EXISTE, "Une unité porte déjà ce code dans l'établissement.", statut=409
        ) from None


def creer_unite(*, par: Any, **champs: Any) -> UniteOrganisationnelle:
    """Crée une unité (``unite.creee``)."""
    if UniteOrganisationnelle.objects.filter(code=champs["code"]).exists():
        raise ErreurApi(
            CODE_EXISTE, "Une unité porte déjà ce code dans l'établissement.", statut=409
        )
    unite = UniteOrganisationnelle(**champs)
    _enregistrer_unite(unite)
    journaliser(
        "unite.creee", Categorie.PARAMETRAGE, objet=unite, apres=extraire_champs(unite), acteur=par
    )
    return unite


def modifier_unite(
    unite: UniteOrganisationnelle, *, par: Any, **champs: Any
) -> UniteOrganisationnelle:
    """Modifie une unité (``unite.modifiee``) ; refuse les cycles dans l'arbre."""
    if "parent" in champs:
        _verifier_parent(unite.id, champs["parent"])
    nouveau_code = champs.get("code", unite.code)
    if (
        nouveau_code != unite.code
        and UniteOrganisationnelle.objects.filter(code=nouveau_code).exclude(id=unite.id).exists()
    ):
        raise ErreurApi(
            CODE_EXISTE, "Une unité porte déjà ce code dans l'établissement.", statut=409
        )
    modifies = [c for c, v in champs.items() if getattr(unite, c) != v]
    if not modifies:
        return unite
    avant = extraire_champs(unite, modifies)
    for cle, valeur in champs.items():
        setattr(unite, cle, valeur)
    _enregistrer_unite(unite)
    journaliser(
        "unite.modifiee",
        Categorie.PARAMETRAGE,
        objet=unite,
        avant=avant,
        apres=extraire_champs(unite, modifies),
        acteur=par,
    )
    return unite
