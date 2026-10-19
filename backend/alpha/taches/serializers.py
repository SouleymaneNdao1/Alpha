"""Représentation API des tâches (objet ``Tache`` du § 5.1)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Action, Groupe, Module
from .visibilite import ORDRE_GROUPES, Bornes


class DelegantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()


class TacheSerializer(serializers.Serializer):
    """Lecture seule ; contexte : ``bornes`` (``Bornes``) et ``delegants`` ({uuid: nom})."""

    id = serializers.UUIDField()
    module = serializers.ChoiceField(choices=Module.choices)
    module_libelle = serializers.SerializerMethodField()
    reference = serializers.CharField()
    titre = serializers.CharField()
    sous_titre = serializers.CharField()
    montant = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    devise = serializers.CharField()
    action = serializers.ChoiceField(choices=Action.choices)
    action_libelle = serializers.SerializerMethodField()
    type_echeance = serializers.CharField()
    echeance = serializers.DateTimeField(allow_null=True)
    groupe = serializers.SerializerMethodField()
    retard_jours = serializers.SerializerMethodField()
    lien = serializers.CharField()
    par_delegation_de = serializers.SerializerMethodField()
    cree_le = serializers.DateTimeField()

    def get_module_libelle(self, tache) -> str:
        return Module(tache.module).label

    def get_action_libelle(self, tache) -> str:
        return Action(tache.action).label

    def _bornes(self) -> Bornes:
        return self.context["bornes"]

    @extend_schema_field(serializers.ChoiceField(choices=Groupe.choices))
    def get_groupe(self, tache) -> str:
        ordre = getattr(tache, "groupe_ordre", None)
        if ordre is not None:
            return ORDRE_GROUPES[ordre]
        return self._bornes().groupe_de(tache.echeance)

    def get_retard_jours(self, tache) -> int | None:
        return self._bornes().retard_jours(tache.echeance)

    @extend_schema_field(DelegantSerializer(allow_null=True))
    def get_par_delegation_de(self, tache) -> dict | None:
        delegant = getattr(tache, "par_delegation_de_id", None)
        if delegant is None:
            return None
        return {"id": delegant, "nom": self.context.get("delegants", {}).get(delegant, "")}


class ComptesGroupesSerializer(serializers.Serializer):
    EN_RETARD = serializers.IntegerField()
    AUJOURDHUI = serializers.IntegerField()
    CETTE_SEMAINE = serializers.IntegerField()
    PLUS_TARD = serializers.IntegerField()


class CompteursSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    par_groupe = ComptesGroupesSerializer()
    par_module = serializers.DictField(
        child=serializers.IntegerField(), help_text="Modules ayant au moins une tâche."
    )
