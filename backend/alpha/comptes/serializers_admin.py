"""Sérialiseurs de l'administration des comptes (§ 5.1 ``UtilisateurListe``, § 5.5 ; tâche B7).

Les réponses sont construites par les fonctions ``presenter_*`` (dictionnaires) ; les
sérialiseurs de sortie décrivent leur forme pour le schéma OpenAPI. Les sérialiseurs
d'entrée valident les corps et résolvent les identifiants DANS l'établissement courant
(un identifiant d'un autre établissement est « inconnu »).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from rest_framework import serializers

from alpha.audit.models import EvenementAudit
from alpha.organisation.models import AffectationRole, UniteOrganisationnelle

from . import raccordements
from .administration import est_verrouille
from .models import StatutUtilisateur, Utilisateur

FORMAT_E164 = r"^\+[1-9][0-9]{6,14}$"
PERIMETRE_ETABLISSEMENT = "Tout l'établissement"


# --- Présentation -----------------------------------------------------------------------------


def initiales(utilisateur: Utilisateur) -> str:
    return f"{utilisateur.prenom[:1]}{utilisateur.nom[:1]}".upper()


def _affectations_en_cours(utilisateur_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list]:
    resultat: dict[uuid.UUID, list[AffectationRole]] = {}
    for affectation in (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id__in=list(utilisateur_ids))
        .select_related("role", "unite")
        .order_by("-principal", "role__ordre", "role__libelle")
    ):
        resultat.setdefault(affectation.utilisateur_id, []).append(affectation)
    return resultat


def presenter_affectation(affectation: AffectationRole) -> dict[str, Any]:
    return {
        "id": affectation.id,
        "role": {"id": affectation.role_id, "libelle": affectation.role.libelle},
        "unite": (
            {"id": affectation.unite_id, "libelle": affectation.unite.libelle}
            if affectation.unite_id
            else None
        ),
        "principal": affectation.principal,
        "debut": affectation.debut,
        "fin": affectation.fin,
    }


def presenter_liste(utilisateurs: list[Utilisateur]) -> list[dict[str, Any]]:
    """Lignes ``UtilisateurListe`` (§ 5.1) ; requêtes groupées pour toute la page."""
    ids = [u.id for u in utilisateurs]
    affectations = _affectations_en_cours(ids)
    authenticators = raccordements.statuts_authenticator(ids)
    lignes = []
    for u in utilisateurs:
        principale = next((a for a in affectations.get(u.id, []) if a.principal), None)
        lignes.append(
            {
                "id": u.id,
                "prenom": u.prenom,
                "nom": u.nom,
                "initiales": initiales(u),
                "email": u.email,
                "role_principal": principale.role.libelle if principale else None,
                "perimetre": (
                    (principale.unite.libelle if principale.unite_id else PERIMETRE_ETABLISSEMENT)
                    if principale
                    else None
                ),
                "authenticator": authenticators.get(
                    u.id, raccordements.AUTHENTICATOR_NON_CONFIGUREE
                ),
                "derniere_connexion": u.derniere_connexion,
                "statut": u.statut,
                "verrouille": est_verrouille(u),
            }
        )
    return lignes


def presenter_detail(utilisateur: Utilisateur) -> dict[str, Any]:
    """Fiche administrateur : identité, état, affectations en cours, sessions, signalement."""
    ligne = presenter_liste([utilisateur])[0]
    responsable = utilisateur.responsable
    return {
        **ligne,
        "telephone_mobile": utilisateur.telephone_mobile,
        "langue": utilisateur.langue,
        "responsable": (
            {"id": responsable.id, "nom": responsable.nom_complet} if responsable else None
        ),
        "echecs_connexion": utilisateur.echecs_connexion,
        "verrouille_jusqua": utilisateur.verrouille_jusqua,
        "bloque_par_admin": utilisateur.bloque_par_admin,
        "mfa_a_reconfigurer": utilisateur.mfa_a_reconfigurer,
        "signature_bloquee": utilisateur.signature_bloquee,
        "active_le": utilisateur.active_le,
        "cree_le": utilisateur.cree_le,
        "affectations": [
            presenter_affectation(a)
            for a in _affectations_en_cours([utilisateur.id]).get(utilisateur.id, [])
        ],
        "sessions_actives": raccordements.sessions_actives(utilisateur.id),
        "signalement": raccordements.signalement_en_cours(utilisateur.id),
    }


# --- Sortie (schéma) ----------------------------------------------------------------------------


class ReferenceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    libelle = serializers.CharField()


class ReferencePersonneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()


class UtilisateurListeSerializer(serializers.Serializer):
    """``UtilisateurListe`` (§ 5.1)."""

    id = serializers.UUIDField()
    prenom = serializers.CharField()
    nom = serializers.CharField()
    initiales = serializers.CharField()
    email = serializers.EmailField()
    role_principal = serializers.CharField(allow_null=True)
    perimetre = serializers.CharField(allow_null=True)
    authenticator = serializers.ChoiceField(
        choices=[
            raccordements.AUTHENTICATOR_ACTIVE,
            raccordements.AUTHENTICATOR_NON_CONFIGUREE,
            raccordements.AUTHENTICATOR_SUSPENDUE,
        ]
    )
    derniere_connexion = serializers.DateTimeField(allow_null=True)
    statut = serializers.ChoiceField(choices=StatutUtilisateur.choices)
    verrouille = serializers.BooleanField()


class PageUtilisateursSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = UtilisateurListeSerializer(many=True)


class AffectationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    role = ReferenceSerializer()
    unite = ReferenceSerializer(allow_null=True)
    principal = serializers.BooleanField()
    debut = serializers.DateField()
    fin = serializers.DateField(allow_null=True)


class SessionActiveSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    appareil = serializers.CharField()
    ip = serializers.IPAddressField(allow_null=True)
    methode_mfa = serializers.CharField()
    cree_le = serializers.DateTimeField()
    derniere_activite = serializers.DateTimeField()


class SignalementSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    statut = serializers.CharField()
    canal = serializers.CharField()
    signale_le = serializers.DateTimeField()


class UtilisateurDetailSerializer(UtilisateurListeSerializer):
    """Fiche administrateur (``GET /admin/utilisateurs/{id}``)."""

    telephone_mobile = serializers.CharField(allow_null=True)
    langue = serializers.CharField()
    responsable = ReferencePersonneSerializer(allow_null=True)
    echecs_connexion = serializers.IntegerField()
    verrouille_jusqua = serializers.DateTimeField(allow_null=True)
    bloque_par_admin = serializers.BooleanField()
    mfa_a_reconfigurer = serializers.BooleanField()
    signature_bloquee = serializers.BooleanField()
    active_le = serializers.DateTimeField(allow_null=True)
    cree_le = serializers.DateTimeField()
    affectations = AffectationSerializer(many=True)
    sessions_actives = SessionActiveSerializer(many=True)
    signalement = SignalementSerializer(allow_null=True)


class SuspensionReponseSerializer(UtilisateurDetailSerializer):
    sessions_revoquees = serializers.IntegerField()


class InvitationRenvoyeeSerializer(serializers.Serializer):
    expire_le = serializers.DateTimeField()


class RevocationSessionsSerializer(serializers.Serializer):
    revoquees = serializers.IntegerField()


class EvenementAuditSerializer(serializers.Serializer):
    """``EvenementAudit`` (§ 5.1), pour l'historique des actions d'administration."""

    seq = serializers.IntegerField()
    horodatage = serializers.DateTimeField()
    acteur_type = serializers.CharField()
    acteur_libelle = serializers.CharField()
    categorie = serializers.CharField()
    action = serializers.CharField()
    action_libelle = serializers.CharField()
    objet_type = serializers.CharField()
    objet_id = serializers.CharField()
    objet_libelle = serializers.CharField()
    avant = serializers.JSONField(allow_null=True)
    apres = serializers.JSONField(allow_null=True)
    detail = serializers.CharField()
    ip = serializers.IPAddressField(allow_null=True)
    hash = serializers.CharField()
    hash_court = serializers.CharField()


#: Libellés des actions d'administration des comptes (le journal complet relève de B11).
LIBELLES_ACTIONS = {
    "utilisateur.invite": "Invitation",
    "utilisateur.modifie": "Modification du compte",
    "utilisateur.suspendu": "Suspension",
    "utilisateur.reactive": "Réactivation",
    "utilisateur.deverrouille": "Déverrouillage",
    "affectation.creee": "Attribution d'un rôle",
    "affectation.terminee": "Retrait d'un rôle",
    "auth.session.revoquee": "Révocation des sessions",
}


def presenter_evenement(evenement: EvenementAudit) -> dict[str, Any]:
    empreinte = (evenement.hash or "").strip()
    return {
        "seq": evenement.seq,
        "horodatage": evenement.horodatage,
        "acteur_type": evenement.acteur_type,
        "acteur_libelle": evenement.acteur_libelle,
        "categorie": evenement.categorie,
        "action": evenement.action,
        "action_libelle": LIBELLES_ACTIONS.get(evenement.action, evenement.action),
        "objet_type": evenement.objet_type,
        "objet_id": evenement.objet_id,
        "objet_libelle": evenement.objet_libelle,
        "avant": evenement.avant,
        "apres": evenement.apres,
        "detail": evenement.detail,
        "ip": evenement.ip,
        "hash": empreinte,
        "hash_court": f"{empreinte[:4]}…{empreinte[-4:]}" if empreinte else "",
    }


# --- Entrée -------------------------------------------------------------------------------------


def _unite(valeur: uuid.UUID | None) -> UniteOrganisationnelle | None:
    if valeur is None:
        return None
    unite = UniteOrganisationnelle.objects.filter(id=valeur).first()
    if unite is None:
        raise serializers.ValidationError("Unité inconnue.")
    return unite


def _responsable(valeur: uuid.UUID | None) -> Utilisateur | None:
    if valeur is None:
        return None
    responsable = (
        Utilisateur.objects.filter(id=valeur).exclude(statut=StatutUtilisateur.DESACTIVE).first()
    )
    if responsable is None:
        raise serializers.ValidationError("Utilisateur inconnu.")
    return responsable


class InvitationSerializer(serializers.Serializer):
    """Corps de ``POST /admin/utilisateurs`` (§ 4.3)."""

    email = serializers.EmailField(max_length=254)
    prenom = serializers.CharField(max_length=80)
    nom = serializers.CharField(max_length=80)
    role_id = serializers.UUIDField()
    unite_id = serializers.UUIDField(required=False, allow_null=True)
    responsable_id = serializers.UUIDField(required=False, allow_null=True)
    telephone_mobile = serializers.RegexField(
        FORMAT_E164,
        max_length=20,
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages={"invalid": "Format international attendu (ex. +221770000000)."},
    )

    def validate_unite_id(self, valeur):
        return _unite(valeur)

    def validate_responsable_id(self, valeur):
        return _responsable(valeur)


class ModificationUtilisateurSerializer(serializers.Serializer):
    """Corps de ``PATCH /admin/utilisateurs/{id}`` (l'e-mail n'est pas modifiable)."""

    prenom = serializers.CharField(max_length=80, required=False)
    nom = serializers.CharField(max_length=80, required=False)
    telephone_mobile = serializers.RegexField(
        FORMAT_E164,
        max_length=20,
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages={"invalid": "Format international attendu (ex. +221770000000)."},
    )
    responsable_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_responsable_id(self, valeur):
        responsable = _responsable(valeur)
        cible = self.context.get("utilisateur")
        if responsable is not None and cible is not None and responsable.id == cible.id:
            raise serializers.ValidationError(
                "Un utilisateur ne peut pas être son propre responsable."
            )
        return responsable

    def champs_modele(self) -> dict[str, Any]:
        donnees = dict(self.validated_data)
        if "responsable_id" in donnees:
            donnees["responsable"] = donnees.pop("responsable_id")
        for cle in ("prenom", "nom"):
            if cle in donnees:
                donnees[cle] = donnees[cle].strip()
        return donnees


class NouvelleAffectationSerializer(serializers.Serializer):
    """Corps de ``POST /admin/utilisateurs/{id}/affectations``."""

    role_id = serializers.UUIDField()
    unite_id = serializers.UUIDField(required=False, allow_null=True)
    principal = serializers.BooleanField(default=False)

    def validate_unite_id(self, valeur):
        return _unite(valeur)


class SuspensionSerializer(serializers.Serializer):
    """Corps de ``POST /admin/utilisateurs/{id}/suspendre``."""

    motif = serializers.CharField(max_length=500)
