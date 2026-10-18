"""Invariant « dernier administrateur » et paramètres de sécurité (tâche B7, § 2.3, § 5.5, § 10)."""

from __future__ import annotations

from unittest import mock

import pytest

from alpha.comptes import raccordements
from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.models import AffectationRole, Role
from alpha.organisation.roles_defaut import CODE_ADMINISTRATEUR
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import ParametresEtablissement
from alpha.tenancy.parametres import BORNES

from .fabriques import AffectationRoleFactory, RoleFactory, UtilisateurFactory
from .outils_admin import API, avec_permissions, creer_admin, evenements, relire

pytestmark = pytest.mark.django_db


# --- Invariant « dernier administrateur » --------------------------------------------------------


def _affectation_admin(banque, utilisateur) -> AffectationRole:
    with contexte_tenant(banque.id):
        return AffectationRole.objects.get(utilisateur=utilisateur, role__code=CODE_ADMINISTRATEUR)


def test_dernier_administrateur_ne_peut_pas_se_suspendre(client_admin, banque, admin):
    reponse = client_admin.post(
        f"{API}/utilisateurs/{admin.id}/suspendre", {"motif": "test"}, format="json"
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "DERNIER_ADMINISTRATEUR"
    assert relire(Utilisateur, banque, id=admin.id).statut == StatutUtilisateur.ACTIF
    assert evenements(banque, "utilisateur.suspendu") == []


def test_dernier_administrateur_ne_peut_pas_perdre_son_role(client_admin, banque, admin):
    affectation = _affectation_admin(banque, admin)
    reponse = client_admin.post(f"{API}/affectations/{affectation.id}/terminer")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "DERNIER_ADMINISTRATEUR"
    assert relire(AffectationRole, banque, id=affectation.id).fin is None


def test_suspension_possible_s_il_reste_un_autre_administrateur(client_admin, banque, admin):
    second = creer_admin(banque, email="second@banque.test")
    reponse = client_admin.post(
        f"{API}/utilisateurs/{second.id}/suspendre", {"motif": "départ"}, format="json"
    )
    assert reponse.status_code == 200
    # Le premier devient le dernier : il ne peut plus être retiré.
    affectation = _affectation_admin(banque, admin)
    assert client_admin.post(f"{API}/affectations/{affectation.id}/terminer").status_code == 409


def test_administrateur_suspendu_ne_compte_pas(client_admin, banque, admin):
    """Un second titulaire SUSPENDU (ou INVITE) ne sauve pas l'invariant."""
    creer_admin(banque, email="suspendu@banque.test", statut=StatutUtilisateur.SUSPENDU)
    creer_admin(banque, email="invite@banque.test", statut=StatutUtilisateur.INVITE)
    reponse = client_admin.post(
        f"{API}/utilisateurs/{admin.id}/suspendre", {"motif": "x"}, format="json"
    )
    assert reponse.status_code == 409


def test_role_non_systeme_porteur_d_admin_utilisateurs(client_connecte, banque):
    """Retirer la permission (ou désactiver le rôle) du dernier titulaire est refusé."""
    gestionnaire = avec_permissions(
        banque, CodePermission.ADMIN_UTILISATEURS, CodePermission.ADMIN_ROLES
    )
    client = client_connecte(gestionnaire)
    son_role = relire(Role, banque, affectations__utilisateur=gestionnaire)

    retrait = client.patch(
        f"{API}/roles/{son_role.id}", {"permissions": ["admin.roles"]}, format="json"
    )
    assert retrait.status_code == 409 and retrait.json()["code"] == "DERNIER_ADMINISTRATEUR"
    assert client.post(f"{API}/roles/{son_role.id}/desactiver").status_code == 409
    relu = relire(Role, banque, id=son_role.id)
    assert relu.actif and set(relu.permissions) == {"admin.utilisateurs", "admin.roles"}
    # Avec un autre administrateur actif, l'opération passe.
    creer_admin(banque, email="autre@banque.test")
    assert client.post(f"{API}/roles/{son_role.id}/desactiver").status_code == 200


def test_invariant_sans_administrateur_prealable_ne_bloque_pas(client_connecte, banque):
    """Établissement sans aucun administrateur actif : rien n'est retiré, rien n'est bloqué."""
    gestionnaire = avec_permissions(banque, CodePermission.ADMIN_ROLES)
    client = client_connecte(gestionnaire)
    autre = RoleFactory(etablissement=banque, permissions=["admin.utilisateurs"])
    titulaire = UtilisateurFactory(etablissement=banque, statut=StatutUtilisateur.SUSPENDU)
    AffectationRoleFactory(utilisateur=titulaire, role=autre)
    assert client.post(f"{API}/roles/{autre.id}/desactiver").status_code == 200


# --- Paramètres de sécurité -----------------------------------------------------------------------


@pytest.fixture
def step_up_accepte():
    with mock.patch.object(raccordements, "verifier_code_step_up", return_value=True) as verif:
        yield verif


def test_lire_parametres_securite(client_admin):
    reponse = client_admin.get(f"{API}/parametres-securite")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["inactivite_session_min"] == 15
    assert corps["duree_max_session_h"] == 12
    assert corps["validite_invitation_h"] == 72
    assert corps["mdp_expiration_jours"] is None
    assert corps["email_controle_interne"] == ""
    assert {"verrouillages_max_24h", "validite_reinit_mdp_min", "modifie_le"} <= set(corps)


def test_modifier_parametres_securite_et_audit(client_admin, banque, admin, step_up_accepte):
    reponse = client_admin.patch(
        f"{API}/parametres-securite",
        {
            "code": "123456",
            "inactivite_session_min": 30,
            "mdp_expiration_jours": 90,
            "email_controle_interne": "controle@banque.test",
            "tentatives_max": 5,  # inchangé : absent de l'audit
        },
        format="json",
    )
    assert reponse.status_code == 200, reponse.json()
    assert reponse.json()["inactivite_session_min"] == 30
    step_up_accepte.assert_called_once_with(admin.id, "123456")
    with contexte_tenant(banque.id):
        parametres = ParametresEtablissement.objects.get()
    assert (parametres.inactivite_session_min, parametres.mdp_expiration_jours) == (30, 90)
    (evt,) = evenements(banque, "parametres.securite.modifies")
    assert evt.categorie == "PARAMETRAGE"
    assert evt.avant == {
        "inactivite_session_min": 15,
        "mdp_expiration_jours": None,
        "email_controle_interne": "",
    }
    assert evt.apres == {
        "inactivite_session_min": 30,
        "mdp_expiration_jours": 90,
        "email_controle_interne": "controle@banque.test",
    }
    assert "123456" not in evt.payload_canonique

    # Retour à « pas d'expiration ».
    reponse = client_admin.patch(
        f"{API}/parametres-securite",
        {"code": "123456", "mdp_expiration_jours": None},
        format="json",
    )
    assert reponse.json()["mdp_expiration_jours"] is None


@pytest.mark.parametrize("champ", sorted(BORNES))
def test_bornes_des_parametres(client_admin, banque, step_up_accepte, champ):
    minimum, maximum = BORNES[champ]
    for valeur in (minimum - 1, maximum + 1):
        reponse = client_admin.patch(
            f"{API}/parametres-securite", {"code": "123456", champ: valeur}, format="json"
        )
        assert reponse.status_code == 400, (champ, valeur)
        assert reponse.json()["code"] == "VALIDATION"
        assert champ in reponse.json()["details"]
    for valeur in (minimum, maximum):
        reponse = client_admin.patch(
            f"{API}/parametres-securite", {"code": "123456", champ: valeur}, format="json"
        )
        assert reponse.status_code == 200, (champ, valeur, reponse.json())
        assert reponse.json()[champ] == valeur


def test_parametres_validation_divers(client_admin, step_up_accepte):
    reponse = client_admin.patch(
        f"{API}/parametres-securite",
        {"code": "123456", "email_controle_interne": "pas-un-email", "tentatives_max": "beaucoup"},
        format="json",
    )
    assert reponse.status_code == 400
    assert {"email_controle_interne", "tentatives_max"} <= set(reponse.json()["details"])
    sans_code = client_admin.patch(
        f"{API}/parametres-securite", {"tentatives_max": 4}, format="json"
    )
    assert sans_code.status_code == 400 and "code" in sans_code.json()["details"]
    step_up_accepte.assert_not_called()


def test_parametres_step_up_refuse_par_defaut(client_admin, banque):
    """Tant que B5 n'est pas livré, le step-up échoue fermé : aucun réglage n'est modifié."""
    reponse = client_admin.patch(
        f"{API}/parametres-securite", {"code": "123456", "tentatives_max": 4}, format="json"
    )
    assert reponse.status_code == 401 and reponse.json()["code"] == "CODE_INVALIDE"
    with contexte_tenant(banque.id):
        assert ParametresEtablissement.objects.get().tentatives_max == 5
    assert evenements(banque, "parametres.securite.modifies") == []


def test_parametres_exigent_admin_securite(client_connecte, banque, step_up_accepte):
    gestionnaire = avec_permissions(banque, CodePermission.ADMIN_UTILISATEURS)
    client = client_connecte(gestionnaire)
    assert client.get(f"{API}/parametres-securite").status_code == 403
    reponse = client.patch(
        f"{API}/parametres-securite", {"code": "123456", "tentatives_max": 4}, format="json"
    )
    assert reponse.status_code == 403
    step_up_accepte.assert_not_called()
