"""Accès à l'API d'administration : permissions, isolation entre établissements, super-admin,
schéma OpenAPI (tâche B7, § 3.8, § 5)."""

from __future__ import annotations

import pytest
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema

from alpha.organisation.codes_permission import CodePermission as C
from alpha.organisation.models import Role
from alpha.tenancy.contexte import contexte_tenant

from .fabriques import AffectationRoleFactory, UniteOrganisationnelleFactory, UtilisateurFactory
from .outils_admin import API, avec_permissions, creer_admin, role

pytestmark = pytest.mark.django_db

U, R, ORG, S = C.ADMIN_UTILISATEURS, C.ADMIN_ROLES, C.ADMIN_ORGANISATION, C.ADMIN_SECURITE

#: (méthode, chemin, permissions acceptées) de chaque route livrée par B7.
ROUTES = [
    ("get", "/utilisateurs", {U}),
    ("post", "/utilisateurs", {U}),
    ("get", "/utilisateurs/historique", {U}),
    ("get", "/utilisateurs/{utilisateur}", {U}),
    ("patch", "/utilisateurs/{utilisateur}", {U}),
    ("post", "/utilisateurs/{utilisateur}/affectations", {U}),
    ("post", "/utilisateurs/{utilisateur}/suspendre", {U}),
    ("post", "/utilisateurs/{utilisateur}/reactiver", {U}),
    ("post", "/utilisateurs/{utilisateur}/deverrouiller", {U}),
    ("post", "/utilisateurs/{utilisateur}/renvoyer-invitation", {U}),
    ("post", "/utilisateurs/{utilisateur}/sessions/revoquer", {U}),
    ("post", "/affectations/{affectation}/terminer", {U}),
    ("get", "/roles", {R, U}),
    ("post", "/roles", {R}),
    ("patch", "/roles/{role}", {R}),
    ("post", "/roles/{role}/desactiver", {R}),
    ("post", "/roles/{role}/activer", {R}),
    ("get", "/permissions", {R}),
    ("get", "/unites", {ORG, U}),
    ("post", "/unites", {ORG}),
    ("patch", "/unites/{unite}", {ORG}),
    ("get", "/parametres-securite", {S}),
    ("patch", "/parametres-securite", {S}),
]
ROUTES_OBJET = [r for r in ROUTES if "{" in r[1]]


@pytest.fixture
def objets(banque):
    """Un objet de chaque type dans ``banque`` : utilisateur, affectation, rôle, unité."""
    cible = UtilisateurFactory(etablissement=banque, email="cible@banque.test")
    affectation = AffectationRoleFactory(
        utilisateur=cible, role=role(banque, "juriste"), principal=True
    )
    return {
        "utilisateur": cible.id,
        "affectation": affectation.id,
        "role": role(banque, "daf").id,
        "unite": UniteOrganisationnelleFactory(etablissement=banque).id,
    }


def _appeler(client, methode, chemin, objets):
    return getattr(client, methode)(f"{API}{chemin.format(**objets)}", {}, format="json")


@pytest.mark.parametrize(("methode", "chemin", "perms"), ROUTES)
def test_anonyme_refuse_401(client_api, objets, methode, chemin, perms):
    reponse = _appeler(client_api, methode, chemin, objets)
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "NON_AUTHENTIFIE"


@pytest.mark.parametrize(("methode", "chemin", "perms"), ROUTES)
def test_super_admin_fyxop_refuse_403(client_connecte, objets, methode, chemin, perms):
    client = client_connecte(UtilisateurFactory(super_admin=True))
    reponse = _appeler(client, methode, chemin, objets)
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "PERMISSION_REFUSEE"


@pytest.mark.parametrize(("methode", "chemin", "perms"), ROUTES)
def test_utilisateur_sans_la_permission_refuse_403(
    client_connecte, banque, objets, methode, chemin, perms
):
    # Toutes les permissions système SAUF celles qui ouvrent la route.
    autres = [c for c in C.values if c not in perms]
    client = client_connecte(avec_permissions(banque, *autres))
    reponse = _appeler(client, methode, chemin, objets)
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "PERMISSION_REFUSEE"


@pytest.mark.parametrize(("methode", "chemin", "perms"), ROUTES)
def test_chaque_permission_acceptee_ouvre_la_route(
    client_connecte, banque, objets, methode, chemin, perms
):
    """Avec la permission (une seule à la fois), la route ne répond jamais 401/403."""
    for code in perms:
        client = client_connecte(avec_permissions(banque, code))
        reponse = _appeler(client, methode, chemin, objets)
        assert reponse.status_code not in (401, 403), (code, reponse.json())


@pytest.mark.parametrize(("methode", "chemin", "perms"), ROUTES_OBJET)
def test_admin_de_a_n_atteint_rien_de_b_404(client_admin, autre_banque, methode, chemin, perms):
    """Identifiants d'un autre établissement : 404, jamais 403 (§ 5)."""
    cible = UtilisateurFactory(etablissement=autre_banque)
    objets_b = {
        "utilisateur": cible.id,
        "affectation": AffectationRoleFactory(
            utilisateur=cible, role=role(autre_banque, "daf"), principal=True
        ).id,
        "role": role(autre_banque, "juriste").id,
        "unite": UniteOrganisationnelleFactory(etablissement=autre_banque).id,
    }
    reponse = _appeler(client_admin, methode, chemin, objets_b)
    assert reponse.status_code == 404
    assert reponse.json()["code"] == "INTROUVABLE"


def test_listes_limitees_a_l_etablissement(client_admin, banque, autre_banque):
    creer_admin(autre_banque, email="admin@autre.test")
    UniteOrganisationnelleFactory(etablissement=autre_banque, libelle="Unité de B")
    emails = [u["email"] for u in client_admin.get(f"{API}/utilisateurs").json()["results"]]
    assert "admin@autre.test" not in emails
    with contexte_tenant(autre_banque.id):
        ids_roles_b = {str(i) for i in Role.objects.values_list("id", flat=True)}
    ids_roles_a = {r["id"] for r in client_admin.get(f"{API}/roles").json()}
    assert ids_roles_a and not ids_roles_a & ids_roles_b
    assert "Unité de B" not in str(client_admin.get(f"{API}/unites").json())
    historique = client_admin.get(f"{API}/utilisateurs/historique?limite=50").json()
    assert all(e["objet_libelle"] != "admin@autre.test" for e in historique)


def test_admin_de_a_ne_peut_pas_affecter_un_role_de_b(client_admin, banque, autre_banque):
    cible = UtilisateurFactory(etablissement=banque)
    reponse = client_admin.post(
        f"{API}/utilisateurs/{cible.id}/affectations",
        {"role_id": str(role(autre_banque, "daf").id)},
        format="json",
    )
    assert reponse.status_code == 400 and reponse.json()["code"] == "ROLE_HORS_CATALOGUE"


# --- Schéma OpenAPI ------------------------------------------------------------


def test_schema_openapi_valide_et_complet():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    validate_schema(schema)
    chemins = schema["paths"]
    for methode, chemin, _ in ROUTES:
        gabarit = (
            chemin.replace("{utilisateur}", "{utilisateur_id}")
            .replace("{affectation}", "{affectation_id}")
            .replace("{role}", "{role_id}")
            .replace("{unite}", "{unite_id}")
        )
        operation = chemins[f"/api/v1/admin{gabarit}"][methode]
        assert {"401", "403"} <= set(operation["responses"]), (methode, chemin)


def test_schema_servi(client_api):
    assert client_api.get("/api/v1/schema/").status_code == 200
