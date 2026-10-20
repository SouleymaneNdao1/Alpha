"""Jeu de données complet d'un établissement, pour les tests d'isolation (tâche T2).

``semer(etab)`` crée, dans l'établissement, au moins UNE ligne dans chaque table
d'établissement du sprint 1 (utilisateurs, comptes équipés, sessions d'appareil, jetons,
signalement, organisation, tâche, absence, délégation, notifications, audit, contrôle
d'intégrité, note de test). Le test ``test_la_graine_couvre_toutes_les_tables`` (T2) échoue si
une nouvelle table d'établissement apparaît sans être semée ici : il faut alors l'ajouter.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from django.test import Client
from django.utils import timezone

from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.audit.verification import lancer_verification
from alpha.comptes import jetons
from alpha.comptes.models import (
    CanalSignalement,
    ObjetJeton,
    SessionAppareil,
    SignalementTelephonePerdu,
    Utilisateur,
)
from alpha.comptes.mots_de_passe import definir_mot_de_passe
from alpha.delegations.models import Absence, Delegation, StatutAbsence, StatutDelegation
from alpha.notifications import services as notifications
from alpha.organisation.models import AffectationRole
from alpha.taches import services as taches
from alpha.taches.models import Action, Module, Tache
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement
from tests.appli_test.models import NoteTest
from tests.outils_auth import creer_compte
from tests.outils_b8 import OrganisationB8, organisation_b8


@dataclass
class Graine:
    """Identifiants d'un établissement semé ; ``admin`` détient TOUTES les permissions."""

    etab: Etablissement
    org: OrganisationB8
    admin: Utilisateur
    cible: Utilisateur
    tache_id: uuid.UUID
    absence_id: uuid.UUID
    delegation_id: uuid.UUID
    notification_id: uuid.UUID
    session_id: uuid.UUID
    signalement_id: uuid.UUID
    unite_id: uuid.UUID
    role_id: uuid.UUID
    affectation_id: uuid.UUID

    def identifiants(self) -> dict[str, uuid.UUID]:
        """Valeur de chaque paramètre ``<uuid:...>`` des routes d'établissement."""
        return {
            "utilisateur_id": self.cible.id,
            "affectation_id": self.affectation_id,
            "signalement_id": self.signalement_id,
            "role_id": self.role_id,
            "unite_id": self.unite_id,
            "tache_id": self.tache_id,
            "absence_id": self.absence_id,
            "delegation_id": self.delegation_id,
            "notification_id": self.notification_id,
            "session_id": self.session_id,
        }


def semer(etab: Etablissement) -> Graine:
    from tests.fabriques import AffectationRoleFactory, RoleFactory  # éviter un cycle d'import

    org = organisation_b8(etab)
    # Administrateur : rôle portant TOUTES les permissions système.
    from alpha.organisation.codes_permission import CodePermission

    role_total = RoleFactory(
        etablissement=etab, code="tout", permissions=list(CodePermission.values)
    )
    admin = org.admin
    AffectationRoleFactory(
        utilisateur=admin, role=role_total, principal=False, debut=datetime.date(2020, 1, 1)
    )
    with contexte_tenant(etab.id):
        affectation = AffectationRole.objects.filter(utilisateur=org.awa).first()
        maintenant = timezone.now()

        # Compte équipé (authenticator, codes de secours, historique de mots de passe).
        compte = creer_compte(etab, email=f"cible@{etab.code}.test")
        cible = compte.utilisateur
        definir_mot_de_passe(cible, "Zephyr-Quartz-Lune-#8")

        # Jeton à usage unique, signalement de téléphone perdu.
        jetons.emettre(cible, ObjetJeton.REINIT_MDP, datetime.timedelta(minutes=30), par=admin)
        signalement = SignalementTelephonePerdu.objects.create(
            etablissement=etab,
            utilisateur=org.fatou,
            canal=CanalSignalement.MON_COMPTE,
            signale_le=maintenant,
        )

        # Tâche, absence, délégation.
        tache = taches.ouvrir(
            ("tests.t2", uuid.uuid4()),
            module=Module.CREDIT,
            action=Action.DECIDER,
            titre=f"Dossier {etab.code}",
            assigne_utilisateur=admin,
        )
        absence = Absence.objects.create(
            etablissement=etab,
            utilisateur=org.awa,
            debut=maintenant + datetime.timedelta(days=30),
            fin=maintenant + datetime.timedelta(days=35),
            motif="CONGE",
            statut=StatutAbsence.SOUMISE,
            valideur=org.mamadou,
        )
        delegation = Delegation.objects.create(
            etablissement=etab,
            absence=absence,
            delegant=org.awa,
            delegataire=org.cheikh,
            debut=absence.debut,
            fin=absence.fin,
            statut=StatutDelegation.EN_ATTENTE,
        )

        # Préférences (créées à l'invitation) et notification.
        notifications.creer_preferences_defaut(admin)
        (notification,) = notifications.notifier(
            [admin], type="test.t2", titre=f"Notification {etab.code}"
        )

        # Audit : événements + contrôle d'intégrité.
        journaliser("test.t2.evenement", Categorie.MODIFICATION, detail=etab.code)
        NoteTest.objects.create(etablissement=etab, texte=f"note {etab.code}")

    # Session d'appareil réelle de l'administrateur (comme à la connexion).
    from tests.conftest import ouvrir_session

    ouvrir_session(Client(), admin)
    lancer_verification(etab.id)
    with contexte_tenant(etab.id):
        session_id = SessionAppareil.objects.filter(utilisateur=admin).values_list("id", flat=True)[
            0
        ]
        tache_id = Tache.objects.get(pk=tache.pk).pk
    return Graine(
        etab=etab,
        org=org,
        admin=admin,
        cible=cible,
        tache_id=tache_id,
        absence_id=absence.pk,
        delegation_id=delegation.pk,
        notification_id=notification.pk,
        session_id=session_id,
        signalement_id=signalement.pk,
        unite_id=org.agence.pk,
        role_id=org.analyste.pk,
        affectation_id=affectation.pk,
    )
