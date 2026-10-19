"""Rechiffre les secrets TOTP avec la clé courante (rotation, architecture § 4.9).

    python manage.py rechiffrer_secrets

À lancer en ``alpha_owner`` (service migrate / exploitation) après avoir placé
la nouvelle clé en tête de ``ALPHA_CLES_CHIFFREMENT`` et incrémenté
``ALPHA_CLES_CHIFFREMENT_VERSION``. Aucun secret n'est affiché.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from alpha.comptes import chiffrement
from alpha.comptes.models import AuthenticatorTOTP


class Command(BaseCommand):
    help = "Rechiffre les secrets TOTP avec la clé de chiffrement courante."

    def handle(self, *args, **options):
        version = chiffrement.version_courante()
        nombre = 0
        with transaction.atomic():
            lignes = AuthenticatorTOTP.objets_globaux.select_for_update().exclude(
                cle_version=version
            )
            for authenticator in lignes:
                authenticator.secret_chiffre = chiffrement.rechiffrer(authenticator.secret_chiffre)
                authenticator.cle_version = version
                # Écriture directe : le contrôle tenant de save() n'a pas lieu d'être ici.
                AuthenticatorTOTP.objets_globaux.filter(pk=authenticator.pk).update(
                    secret_chiffre=authenticator.secret_chiffre, cle_version=version
                )
                nombre += 1
        self.stdout.write(f"{nombre} secret(s) rechiffré(s) avec la clé version {version}.")
