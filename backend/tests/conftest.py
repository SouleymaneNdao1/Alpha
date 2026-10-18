"""Infrastructure de test (tâche T1, § 8) — voir ``docs/tests.md``.

1. La base de test est créée et migrée par alpha_owner, puis la connexion ``default``
   repasse sous alpha_app : TOUS les tests s'exécutent sous le rôle applicatif, la
   RLS s'applique réellement. L'alias ``proprietaire`` (alpha_owner) reste disponible
   pour les tests qui contournent volontairement les protections (``tests/bd.py``).
2. Le vidage des tests transactionnels (TRUNCATE) est fait par alpha_owner, trigger
   d'immutabilité du journal d'audit désactivé le temps du vidage.
3. Fixtures communes : établissements A (banque) et B (SFD), contextes tenant,
   utilisateurs, client API connecté, Mailpit (sauté s'il ne répond pas).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from unittest import mock

import pytest
from django.conf import settings
from django.db import connections
from django.db.backends.postgresql.operations import DatabaseOperations
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from alpha.comptes.models import Utilisateur
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement

from .bd import ALIAS_PROPRIETAIRE, default_en_proprietaire, role_courant
from .fabriques import (
    MOT_DE_PASSE_TEST,
    EtablissementFactory,
    UtilisateurFactory,
)
from .mailpit import ClientMailpit

# --- 1. Création de la base par alpha_owner, tests sous alpha_app -------------------------

_IDENTITE = ("USER", "PASSWORD")
_identite_app: dict[str, str] = {}


def _poser_identite(identite: dict[str, str]) -> None:
    connexion = connections["default"]
    connexion.close()
    connexion.settings_dict.update(identite)


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings_parallel_suffix: None) -> None:
    """Avant ``setup_databases`` : « default » prend l'identité d'alpha_owner (CREATEDB)."""
    reglages = connections["default"].settings_dict
    _identite_app.update({cle: reglages[cle] for cle in _IDENTITE})
    proprietaire = connections.settings[ALIAS_PROPRIETAIRE]
    _poser_identite({cle: proprietaire[cle] for cle in _IDENTITE})


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: None, django_db_blocker) -> Iterator[None]:
    """Après création et migration : « default » repasse sous alpha_app pour les tests."""
    with django_db_blocker.unblock():
        _poser_identite(_identite_app)
        role = role_courant()
        if role != settings.ALPHA_DB_APP_ROLE:
            raise RuntimeError(
                f"Les tests doivent tourner sous {settings.ALPHA_DB_APP_ROLE}, pas sous {role}."
            )
        connections["default"].close()
    yield
    # Suppression de la base de test (fixture parente) : de nouveau par alpha_owner.
    with django_db_blocker.unblock():
        connections.close_all()
        proprietaire = connections.settings[ALIAS_PROPRIETAIRE]
        _poser_identite({cle: proprietaire[cle] for cle in _IDENTITE})


# --- 2. Vidage des tests transactionnels par alpha_owner ----------------------------------
# alpha_app n'a pas le droit TRUNCATE ; le vidage (TRUNCATE de « default » après chaque test
# transactionnel) passe donc par alpha_owner. Le trigger evenement_audit_sans_truncate
# refuse même le propriétaire : seul contournement, en test uniquement et LE TEMPS DU
# VIDAGE SEULEMENT, l'encadrer d'un DISABLE/ENABLE TRIGGER (alpha_owner possède la table).
# En dehors de ce vidage, le trigger reste actif (les tests T3 le vérifient).
_TRIGGER_TRUNCATE_AUDIT = "evenement_audit_sans_truncate"
_sql_flush_origine = DatabaseOperations.sql_flush


def _sql_flush_avec_journal_audit(self, style, tables, *args, **kwargs):
    instructions = _sql_flush_origine(self, style, tables, *args, **kwargs)
    if "evenement_audit" not in tables or not instructions:
        return instructions
    return [
        f"ALTER TABLE evenement_audit DISABLE TRIGGER {_TRIGGER_TRUNCATE_AUDIT};",
        *instructions,
        f"ALTER TABLE evenement_audit ENABLE TRIGGER {_TRIGGER_TRUNCATE_AUDIT};",
    ]


_fixture_teardown_origine = TransactionTestCase._fixture_teardown


def _fixture_teardown_proprietaire(self):
    # Seule « default » est vidée (les autres alias sont des miroirs de la même base).
    with (
        default_en_proprietaire(),
        mock.patch.object(DatabaseOperations, "sql_flush", _sql_flush_avec_journal_audit),
    ):
        _fixture_teardown_origine(self)


TransactionTestCase._fixture_teardown = _fixture_teardown_proprietaire


# --- 3. Établissements et contextes ---------------------------------------------------------
# Noms et valeurs repris de B2/B3 (``etab_a`` banque « banque-a », ``etab_b`` SFD « sfd-b ») :
# les tests existants s'en servent tels quels.


def creer_etablissement(code: str, **champs) -> Etablissement:
    """Crée un établissement et ses paramètres (B2 ; passe désormais par les fabriques)."""
    champs.setdefault("raison_sociale", f"Établissement {code}")
    champs.setdefault("type", "BANQUE")
    return EtablissementFactory(code=code, **champs)


@pytest.fixture
def etab_a(db) -> Etablissement:
    """Banque A (code ``banque-a``), avec ses paramètres par défaut."""
    return creer_etablissement("banque-a")


@pytest.fixture
def etab_b(db) -> Etablissement:
    """SFD B (code ``sfd-b``), avec ses paramètres par défaut."""
    return creer_etablissement("sfd-b", type="SFD")


@pytest.fixture
def contexte_a(etab_a) -> Iterator[Etablissement]:
    """Le test s'exécute sous ``contexte_tenant(A)`` (tests non transactionnels)."""
    with contexte_tenant(etab_a.id):
        yield etab_a


@pytest.fixture
def contexte_b(etab_b) -> Iterator[Etablissement]:
    with contexte_tenant(etab_b.id):
        yield etab_b


@pytest.fixture
def utilisateur_a(etab_a) -> Utilisateur:
    """Utilisateur ACTIF de A, mot de passe ``MOT_DE_PASSE_TEST``."""
    return UtilisateurFactory(
        etablissement=etab_a, email="awa.diop@banque-a.test", password=MOT_DE_PASSE_TEST
    )


@pytest.fixture
def utilisateur_b(etab_b) -> Utilisateur:
    return UtilisateurFactory(
        etablissement=etab_b,
        email="moussa.fall@sfd-b.test",
        prenom="Moussa",
        nom="Fall",
        password=MOT_DE_PASSE_TEST,
    )


# --- Client API connecté ------------------------------------------------------------------


def ouvrir_session(client: APIClient, utilisateur: Utilisateur) -> APIClient:
    """Ouvre une session pour ``utilisateur`` SANS passer par la vue de connexion.

    Pour les tests qui ne portent pas sur l'authentification (les tests B5 passent par
    la vraie connexion : ``tests/outils_auth.se_connecter``). Session forgée comme la
    pose ``alpha.comptes.connexion.ouvrir_session`` : ``force_login``, puis ``tenant_id``,
    ``scope`` et ``mfa_le`` dans la session, et ligne ``session_appareil`` exigée par
    ``SessionActiviteMiddleware`` (B5 ; sinon 401 ``SESSION_EXPIREE``).
    """
    from alpha.comptes import sessions as sessions_appareil
    from alpha.comptes.connexion import regles_pour
    from alpha.comptes.models import MethodeMfa

    client.force_login(utilisateur, backend="django.contrib.auth.backends.ModelBackend")
    session = client.session
    if utilisateur.est_super_admin:
        session["scope"] = contexte.SCOPE_PLATFORM
        session.pop("tenant_id", None)
        cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=utilisateur.id)
    else:
        session["scope"] = contexte.SCOPE_TENANT
        session["tenant_id"] = str(utilisateur.etablissement_id)
        cm = contexte_tenant(utilisateur.etablissement_id, utilisateur_id=utilisateur.id)
    session["mfa_le"] = timezone.now().isoformat()
    with cm:
        appareil = sessions_appareil.creer_session_appareil(
            utilisateur,
            session.session_key,
            methode_mfa=MethodeMfa.TOTP,
            duree_max=regles_pour(utilisateur).duree_max,
            user_agent="client de test",
            ip="127.0.0.1",
        )
    session["session_appareil_id"] = str(appareil.id)
    session.save()
    return client


@pytest.fixture
def client_api() -> APIClient:
    """Client DRF anonyme."""
    return APIClient()


@pytest.fixture
def client_connecte(db) -> Callable[[Utilisateur], APIClient]:
    """Fabrique de clients DRF connectés : ``client_connecte(utilisateur_a)``."""

    def _fabriquer(utilisateur: Utilisateur) -> APIClient:
        return ouvrir_session(APIClient(), utilisateur)

    return _fabriquer


# --- E-mails --------------------------------------------------------------------------------


@pytest.fixture
def mailpit(settings) -> ClientMailpit:
    """Boîte de réception Mailpit (envoi SMTP réel) ; test SAUTÉ si Mailpit ne répond pas.

    Sans cette fixture, les e-mails vont au backend en mémoire (``mail.outbox``).
    """
    client = ClientMailpit(
        settings.ALPHA_MAILPIT_API,
        settings.ALPHA_MAILPIT_UTILISATEUR,
        settings.ALPHA_MAILPIT_MOT_DE_PASSE,
    )
    if not client.disponible():
        pytest.skip(f"Mailpit injoignable ({settings.ALPHA_MAILPIT_API}).")
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    return client
