"""Modèle tenant générique pour les tests d'isolation (le S1 n'a qu'une table tenant réelle)."""

import uuid

from django.db import models

from alpha.tenancy.models import TenantModel


class NoteTest(TenantModel):
    """Table tenant ordinaire : ``etablissement`` hérité de ``TenantModel`` (FK non clé)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    texte = models.CharField(max_length=100)

    class Meta:
        db_table = "note_test"

    def __str__(self) -> str:
        return self.texte
