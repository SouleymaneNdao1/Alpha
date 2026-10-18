"""Infrastructure de test (tâche T1, § 8) : critère « pytest tourne sous alpha_app ».

Vérifie le montage lui-même : rôles des connexions, RLS réellement appliquée aux
tests, fabriques avec contexte tenant, utilitaire TOTP et client des e-mails.
Mode d'emploi : ``docs/tests.md``.
"""

from __future__ import annotations

import datetime

import pyotp
import pytest
from django.conf import settings
from django.core import mail
from django.db import connection, connections
from freezegun import freeze_time

from alpha.comptes.models import Utilisateur
from alpha.organisation.models import AffectationRole, Role
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import ParametresEtablissement, TypeEtablissement

from .bd import (
    ALIAS_AUDIT,
    ALIAS_PROPRIETAIRE,
    TOUTES_LES_BASES,
    role_courant,
    sql,
    sql_proprietaire,
)
from .fabriques import (
    MOT_DE_PASSE_TEST,
    AffectationRoleFactory,
    BanqueFactory,
    EtablissementFactory,
    PMEFactory,
    RoleFactory,
    UtilisateurFactory,
)
from .mailpit import ClientMailpit
from .totp import (
    PAS_SECONDES,
    code_courant,
    code_invalide,
    code_precedent,
    code_suivant,
    compteur,
    nouveau_secret,
)

# --- Rôles des connexions (critère de T1) ------------------------------------------------


@pytest.mark.django_db
def test_connexion_default_des_tests_est_alpha_app():
    """Critère T1 : le code testé tourne sous alpha_app, NOBYPASSRLS, non superutilisateur."""
    assert settings.ALPHA_DB_APP_ROLE == "alpha_app"
    assert role_courant() == "alpha_app"
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT current_user, session_user, rolbypassrls, rolsuper, current_database() "
            "FROM pg_roles WHERE rolname = current_user"
        )
        utilisateur, session, bypass, superutilisateur, base = curseur.fetchone()
    assert (utilisateur, session, bypass, superutilisateur) == (
        "alpha_app",
        "alpha_app",
        False,
        False,
    )
    assert base.startswith("test_")  # base de test, jamais la base de travail


@pytest.mark.django_db(transaction=True, databases=TOUTES_LES_BASES)
def test_alias_proprietaire_et_audit():
    """``proprietaire`` = alpha_owner (BYPASSRLS) ; ``audit`` = alpha_app ; même base."""
    assert role_courant(ALIAS_PROPRIETAIRE) == "alpha_owner"
    assert sql(
        ALIAS_PROPRIETAIRE, "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ) == [(True,)]
    assert role_courant(ALIAS_AUDIT) == settings.ALPHA_DB_APP_ROLE
    bases = {sql(alias, "SELECT current_database()")[0][0] for alias in TOUTES_LES_BASES}
    assert len(bases) == 1


@pytest.mark.django_db
def test_la_rls_s_applique_aux_tests(etab_a, utilisateur_a):
    """Sans contexte, alpha_app ne voit aucun utilisateur ; sous le contexte de A, le sien."""
    assert sql("default", "SELECT count(*) FROM utilisateur") == [(0,)]
    with contexte_tenant(etab_a.id):
        assert sql("default", "SELECT email FROM utilisateur") == [(utilisateur_a.email,)]


@pytest.mark.django_db(transaction=True, databases=["default", ALIAS_PROPRIETAIRE])
def test_proprietaire_lit_hors_rls(utilisateur_a, utilisateur_b):
    assert sql("default", "SELECT count(*) FROM utilisateur") == [(0,)]
    assert sql_proprietaire("SELECT count(*) FROM utilisateur") == [(2,)]


@pytest.mark.django_db(transaction=True)
def test_vidage_transactionnel_sous_alpha_owner_puis_retour_a_alpha_app(etab_a):
    """Après le vidage (par alpha_owner) d'un test transactionnel, « default » est alpha_app."""
    assert role_courant() == settings.ALPHA_DB_APP_ROLE
    assert connections["default"].settings_dict["USER"] == settings.ALPHA_DB_APP_ROLE


# --- Fabriques ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_fabrique_etab_avec_parametres():
    banque = BanqueFactory()
    pme = PMEFactory(parametres__inactivite_session_min=30)
    sans = EtablissementFactory(parametres=False)
    assert (banque.type, pme.type) == (TypeEtablissement.BANQUE, TypeEtablissement.PME)
    with contexte_tenant(banque.id):
        assert ParametresEtablissement.objects.count() == 1
    with contexte_tenant(pme.id):
        assert ParametresEtablissement.objects.get().inactivite_session_min == 30
    with contexte_tenant(sans.id):
        assert not ParametresEtablissement.objects.exists()


@pytest.mark.django_db
def test_fabrique_etablissement_roles_par_defaut():
    banque = BanqueFactory(roles_defaut=True)
    with contexte_tenant(banque.id):
        assert Role.objects.count() == 16  # catalogue par défaut d'une banque (§ 2.3)


@pytest.mark.django_db
def test_fabrique_utilisateur():
    utilisateur = UtilisateurFactory(password=MOT_DE_PASSE_TEST)
    sans_mdp = UtilisateurFactory(etablissement=utilisateur.etablissement)
    admin = UtilisateurFactory(super_admin=True)
    assert utilisateur.check_password(MOT_DE_PASSE_TEST)
    assert not sans_mdp.has_usable_password()
    assert admin.est_super_admin and admin.etablissement_id is None
    with contexte_tenant(utilisateur.etablissement_id):
        assert set(Utilisateur.objects.values_list("id", flat=True)) == {
            utilisateur.id,
            sans_mdp.id,
        }


@pytest.mark.django_db
def test_fabriques_role_et_affectation_dans_le_meme_etablissement():
    affectation = AffectationRoleFactory(principal=True)
    etablissement_id = affectation.utilisateur.etablissement_id
    assert affectation.etablissement_id == affectation.role.etablissement_id == etablissement_id
    role = RoleFactory(etablissement=affectation.etablissement, permissions=["admin.utilisateurs"])
    AffectationRoleFactory(utilisateur=affectation.utilisateur, role=role)
    with contexte_tenant(etablissement_id):
        assert AffectationRole.objects.filter(utilisateur=affectation.utilisateur).count() == 2
        assert Role.objects.get(pk=role.pk).permissions == ["admin.utilisateurs"]


# --- Utilitaire TOTP ----------------------------------------------------------------------


def test_totp_codes_acceptes_par_la_fenetre_de_l_application():
    secret = nouveau_secret()
    totp = pyotp.TOTP(secret)  # paramètres de l'application (§ 4.2, étape 8)
    for code in (code_precedent(secret), code_courant(secret), code_suivant(secret)):
        assert totp.verify(code, valid_window=1)
    assert not totp.verify(code_invalide(secret), valid_window=1)


def test_totp_suit_l_horloge_figee():
    secret = nouveau_secret()
    instant = datetime.datetime(2026, 10, 16, 8, 0, 0, tzinfo=datetime.UTC)
    with freeze_time(instant):
        assert compteur() == int(instant.timestamp()) // PAS_SECONDES
        assert code_courant(secret) == pyotp.TOTP(secret).now()
    with freeze_time(instant + datetime.timedelta(seconds=PAS_SECONDES)):
        assert code_courant(secret) == code_suivant(secret, a=instant)


# --- E-mails --------------------------------------------------------------------------------


def test_mailpit_injoignable_detecte():
    assert not ClientMailpit("http://127.0.0.1:9/api/v1").disponible()


def test_fixture_mailpit_envoi_smtp_reel(mailpit):
    """Sauté si Mailpit ne répond pas ; sinon, un e-mail part en SMTP et se relit par l'API."""
    destinataire = "t1.infrastructure@banque-a.test"
    mailpit.supprimer_pour(destinataire)
    assert settings.EMAIL_BACKEND.endswith("smtp.EmailBackend")
    mail.send_mail("Activez votre compte", "Bonjour", "no-reply@alpha.test", [destinataire])
    message = mailpit.attendre_message(destinataire=destinataire, sujet="Activez")
    assert message.sujet == "Activez votre compte"
    assert message.destinataires == [destinataire]
    assert "Bonjour" in message.texte
    mailpit.supprimer_pour(destinataire)
    assert mailpit.messages_pour(destinataire) == []


def test_sans_fixture_mailpit_les_emails_vont_en_memoire():
    mail.send_mail("Sujet", "Corps", "no-reply@alpha.test", ["x@banque-a.test"])
    assert [m.subject for m in mail.outbox] == ["Sujet"]
