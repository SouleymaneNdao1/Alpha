"""Filtres du journal d'audit, communs à la liste et à l'export (architecture § 5.6).

``?q=`` (utilisateur, objet, IP, détail) ``&categorie=A,B`` ``&action=a,b.*``
``&periode=aujourdhui|7j|30j`` ``&du=&au=`` ``&acteur_id=&objet_type=&objet_id=``.

- ``du`` / ``au`` : date (``2026-10-10``, jour entier, bornes incluses, heure de Dakar) ou
  date-heure ISO 8601 ; incompatibles avec ``periode``.
- ``action`` : codes exacts séparés par des virgules ; un code terminé par ``*``
  (``utilisateur.*``) est un préfixe.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import CharField, Q, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import serializers

from alpha.core import contexte

from .models import Categorie, EvenementAudit

PERIODES = {"aujourdhui": 0, "7j": 6, "30j": 29}  # jours à remonter avant aujourd'hui


def _debut_de_journee(jour: dt.date) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(jour, dt.time.min))


def _borne(valeur: str, *, fin: bool) -> dt.datetime:
    """Date (jour entier) ou date-heure ISO 8601 -> instant ; ``fin`` : borne haute EXCLUE."""
    texte = valeur.strip()
    if len(texte) == 10:
        jour = parse_date(texte)
        if jour is not None:
            return _debut_de_journee(jour + dt.timedelta(days=1) if fin else jour)
    instant = parse_datetime(texte)
    if instant is None:
        raise serializers.ValidationError("Date (AAAA-MM-JJ) ou date-heure ISO 8601 attendue.")
    if timezone.is_naive(instant):
        instant = timezone.make_aware(instant)
    return instant + dt.timedelta(microseconds=1) if fin else instant


class FiltresJournalSerializer(serializers.Serializer):
    """Paramètres de filtrage (requête GET) ; sert aussi à décrire le schéma OpenAPI."""

    q = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Recherche libre : utilisateur, objet (libellé, identifiant), IP, détail.",
    )
    categorie = serializers.CharField(
        required=False,
        help_text="Catégories séparées par des virgules : " + ", ".join(Categorie.values) + ".",
    )
    action = serializers.CharField(
        required=False,
        help_text="Codes d'action séparés par des virgules ; `utilisateur.*` : préfixe.",
    )
    periode = serializers.ChoiceField(
        required=False,
        choices=list(PERIODES),
        help_text="Aujourd'hui, 7 ou 30 derniers jours (jour en cours compris). "
        "Incompatible avec du/au.",
    )
    du = serializers.CharField(
        required=False, help_text="Début inclus : AAAA-MM-JJ (minuit) ou date-heure ISO 8601."
    )
    au = serializers.CharField(
        required=False, help_text="Fin incluse : AAAA-MM-JJ (jour entier) ou date-heure ISO 8601."
    )
    acteur_id = serializers.UUIDField(required=False, help_text="Identifiant de l'acteur.")
    objet_type = serializers.CharField(required=False, max_length=60)
    objet_id = serializers.CharField(required=False, max_length=64)

    def validate_categorie(self, valeur: str) -> list[str]:
        categories = [c.strip() for c in valeur.split(",") if c.strip()]
        inconnues = [c for c in categories if c not in Categorie.values]
        if inconnues:
            raise serializers.ValidationError(f"Catégorie inconnue : {', '.join(inconnues)}.")
        return categories

    def validate_action(self, valeur: str) -> list[str]:
        return [a.strip() for a in valeur.split(",") if a.strip()]

    def validate_du(self, valeur: str) -> dt.datetime:
        return _borne(valeur, fin=False)

    def validate_au(self, valeur: str) -> dt.datetime:
        return _borne(valeur, fin=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "periode" in attrs and ("du" in attrs or "au" in attrs):
            raise serializers.ValidationError({"periode": ["Incompatible avec du/au."]})
        if "du" in attrs and "au" in attrs and attrs["du"] >= attrs["au"]:
            raise serializers.ValidationError({"du": ["La date de début suit la date de fin."]})
        return attrs


def lire_filtres(parametres) -> dict[str, Any]:
    """Valide les paramètres de requête (400 ``VALIDATION`` sinon)."""
    entree = FiltresJournalSerializer(data=parametres)
    entree.is_valid(raise_exception=True)
    return dict(entree.validated_data)


def evenements_de_l_etablissement() -> QuerySet[EvenementAudit]:
    """Chaîne de l'établissement courant (la RLS le garantit déjà ; filtre explicite en plus)."""
    return EvenementAudit.objects.filter(etablissement_id=contexte.tenant_courant())


def appliquer_filtres(qs: QuerySet[EvenementAudit], filtres: dict[str, Any]) -> QuerySet:
    if texte := filtres.get("q"):
        qs = qs.annotate(ip_texte=Cast("ip", CharField())).filter(
            Q(acteur_libelle__icontains=texte)
            | Q(objet_libelle__icontains=texte)
            | Q(objet_id__icontains=texte)
            | Q(detail__icontains=texte)
            | Q(ip_texte__icontains=texte)
        )
    if categories := filtres.get("categorie"):
        qs = qs.filter(categorie__in=categories)
    if actions := filtres.get("action"):
        condition = Q()
        for code in actions:
            if code.endswith("*"):
                condition |= Q(action__startswith=code[:-1])
            else:
                condition |= Q(action=code)
        qs = qs.filter(condition)
    if periode := filtres.get("periode"):
        aujourdhui = timezone.localdate()
        debut = _debut_de_journee(aujourdhui - dt.timedelta(days=PERIODES[periode]))
        qs = qs.filter(horodatage__gte=debut)
    if "du" in filtres:
        qs = qs.filter(horodatage__gte=filtres["du"])
    if "au" in filtres:
        qs = qs.filter(horodatage__lt=filtres["au"])
    if "acteur_id" in filtres:
        qs = qs.filter(acteur_id=filtres["acteur_id"])
    if "objet_type" in filtres:
        qs = qs.filter(objet_type=filtres["objet_type"])
    if "objet_id" in filtres:
        qs = qs.filter(objet_id=filtres["objet_id"])
    return qs


def filtres_lisibles(filtres: dict[str, Any]) -> dict[str, Any]:
    """Filtres sous forme JSON simple (trace d'audit de l'export, feuille « Filtres »)."""
    resultat: dict[str, Any] = {}
    for cle, valeur in filtres.items():
        if isinstance(valeur, dt.datetime):
            resultat[cle] = valeur.isoformat()
        elif isinstance(valeur, list):
            resultat[cle] = list(valeur)
        else:
            resultat[cle] = str(valeur)
    return resultat
