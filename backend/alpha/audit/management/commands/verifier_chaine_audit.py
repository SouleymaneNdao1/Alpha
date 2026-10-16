"""Vérification manuelle des chaînes d'audit (architecture § 6.4).

    python manage.py verifier_chaine_audit --etablissement banque-demo
    python manage.py verifier_chaine_audit --plateforme
    python manage.py verifier_chaine_audit --tous            # établissements + plateforme
    python manage.py verifier_chaine_audit --etablissement banque-demo --depuis-seq 5000

Chaque chaîne est vérifiée sous son propre contexte (RLS) et donne un
``ControleIntegriteAudit`` (déclencheur ``MANUEL``). Code de sortie : 0 si
toutes les chaînes sont intactes, 2 si l'une est rompue, 1 en cas d'erreur.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from alpha.audit.models import Declencheur, StatutControle
from alpha.audit.verification import lancer_verification
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement


class Command(BaseCommand):
    help = "Vérifie l'intégrité de la chaîne d'empreintes du journal d'audit."

    def add_arguments(self, parser: CommandParser) -> None:
        cible = parser.add_mutually_exclusive_group(required=True)
        cible.add_argument("--etablissement", metavar="CODE", help="code de l'établissement")
        cible.add_argument("--plateforme", action="store_true", help="chaîne de la plateforme")
        cible.add_argument(
            "--tous", action="store_true", help="tous les établissements et la plateforme"
        )
        parser.add_argument(
            "--depuis-seq", type=int, default=None, metavar="N", help="commencer au rang N"
        )

    def _etablissements(self, code: str | None) -> list[tuple[str, object]]:
        with contexte_tenant(None, scope=contexte.SCOPE_WORKER, utilisateur_id=None):
            requete = Etablissement.objects.order_by("code")
            if code is not None:
                requete = requete.filter(code=code)
            lignes = [(e.code, e.id) for e in requete]
        if code is not None and not lignes:
            raise CommandError(f"Établissement inconnu : {code}.")
        return lignes

    def handle(self, *args, **options) -> None:
        depuis = options["depuis_seq"]
        if depuis is not None and depuis < 1:
            raise CommandError("--depuis-seq doit être supérieur ou égal à 1.")

        chaines: list[tuple[str, object]] = []
        if options["etablissement"] or options["tous"]:
            chaines += self._etablissements(options["etablissement"])
        if options["plateforme"] or options["tous"]:
            chaines.append(("plateforme", None))

        statuts = []
        for libelle, etablissement_id in chaines:
            controle = lancer_verification(etablissement_id, Declencheur.MANUEL, depuis_seq=depuis)
            statuts.append(controle.statut)
            ligne = (
                f"{libelle} : {controle.statut} — {controle.nb_evenements} événement(s), "
                f"dernier seq {controle.dernier_seq or 0}. {controle.message}"
            )
            if controle.statut == StatutControle.INTACTE:
                self.stdout.write(self.style.SUCCESS(ligne))
            else:
                self.stderr.write(self.style.ERROR(ligne))

        if StatutControle.ROMPUE in statuts:
            raise CommandError("Au moins une chaîne d'audit est rompue.", returncode=2)
        if StatutControle.ERREUR in statuts:
            raise CommandError("Erreur pendant la vérification.", returncode=1)
