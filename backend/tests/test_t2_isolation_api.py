"""T2 · Matrice d'isolation de l'API, générée à partir du routeur.

Un utilisateur de A (administrateur détenant TOUTES les permissions, pour que seul l'isolation
puisse refuser) appelle chaque route d'établissement avec des identifiants appartenant à B :
réponse 404 ``INTROUVABLE`` (convention § 5 : jamais 403, qui confirmerait l'existence), et
aucune donnée de B dans la réponse. Les routes sont énumérées depuis le résolveur d'URL : une
route ajoutée sans identifiant connu (paramètre inconnu de ``Graine.identifiants``) ou sans
être couverte fait échouer ``test_tous_les_parametres_de_route_sont_connus``.

Le super-admin FYXOP sans accès aux routes d'établissement et l'utilisateur d'établissement
sans accès à ``/plateforme`` sont vérifiés dans ``test_b10_plateforme.py`` ; la dernière section
rappelle ici le lien avec cette énumération.
"""

from __future__ import annotations

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from tests.outils_t2 import semer

pytestmark = pytest.mark.django_db

PREFIXES_HORS_ETABLISSEMENT = (
    "api/v1/plateforme/",
    "api/v1/auth/",
    "api/v1/sante/",
    "api/v1/schema",
    "api/v1/docs",
)
METHODES = ("get", "post", "put", "patch", "delete")
PARAMETRE = re.compile(r"<(?:\w+:)?(\w+)>")


def _routes_d_etablissement() -> list[tuple[str, str]]:
    """(méthode, gabarit de chemin) de chaque route d'établissement de l'API."""
    resultat: list[tuple[str, str]] = []

    def parcourir(motifs, prefixe=""):
        for motif in motifs:
            chemin = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                parcourir(motif.url_patterns, chemin)
            elif isinstance(motif, URLPattern):
                vue = getattr(motif.callback, "view_class", None)
                if vue is None or not chemin.startswith("api/v1/"):
                    continue
                if chemin.startswith(PREFIXES_HORS_ETABLISSEMENT):
                    continue
                for methode in METHODES:
                    if hasattr(vue, methode):
                        resultat.append((methode, "/" + chemin))

    parcourir(get_resolver().url_patterns)
    return sorted(resultat)


ROUTES = _routes_d_etablissement()
ROUTES_A_PARAMETRES = [(m, c) for m, c in ROUTES if PARAMETRE.search(c)]
ROUTES_SANS_PARAMETRE = [(m, c) for m, c in ROUTES if not PARAMETRE.search(c)]


@pytest.fixture
def mondes(etab_a, etab_b):
    return semer(etab_a), semer(etab_b)


@pytest.fixture
def client_a(mondes, client_connecte):
    return client_connecte(mondes[0].admin)


def _url(gabarit: str, identifiants: dict) -> str:
    return PARAMETRE.sub(lambda m: str(identifiants[m.group(1)]), gabarit.replace("<uuid:", "<"))


#: Corps valide « pour tout » : les champs inconnus d'une route sont ignorés, de sorte que la
#: validation du corps passe et que seule la recherche de l'objet (404) répond.
CORPS = {
    "code": "000000",
    "mode_verification": "VISIO",
    "commentaire": "",
    "motif": "test",
    "libelle": "x",
}


def _appeler(client, methode, url):
    return getattr(client, methode)(url, CORPS, format="json")


# --- Garde-fous -------------------------------------------------------------------------------


def test_tous_les_parametres_de_route_sont_connus(mondes):
    """Une route à paramètre nouveau doit être ajoutée à ``Graine.identifiants`` (T2)."""
    connus = set(mondes[0].identifiants())
    inconnus = {p for _, c in ROUTES for p in PARAMETRE.findall(c)} - connus
    assert not inconnus, f"Paramètres de route sans identifiant de test : {sorted(inconnus)}"


def test_l_enumeration_voit_les_routes_attendues():
    chemins = {c for _, c in ROUTES}
    for attendu in (
        "/api/v1/taches",
        "/api/v1/taches/<uuid:tache_id>",
        "/api/v1/admin/absences",
        "/api/v1/admin/delegations/<uuid:delegation_id>/revoquer",
        "/api/v1/moi/absences",
        "/api/v1/absences/<uuid:absence_id>/valider",
        "/api/v1/moi/notifications/<uuid:notification_id>/lue",
        "/api/v1/moi/sessions/<uuid:session_id>",
        "/api/v1/admin/utilisateurs/<uuid:utilisateur_id>",
        "/api/v1/admin/roles/<uuid:role_id>/desactiver",
        "/api/v1/admin/unites/<uuid:unite_id>",
        "/api/v1/audit/evenements",
    ):
        assert attendu in chemins, attendu
    assert len(ROUTES_A_PARAMETRES) >= 20


# --- Identifiants de B : 404 ------------------------------------------------------------------


def test_matrice_identifiants_de_b_donnent_404(mondes, client_a):
    """Toutes les routes à paramètres, toutes les méthodes : 404 INTROUVABLE, sans fuite."""
    _, b = mondes
    identifiants_b = b.identifiants()
    secrets_de_b = [str(b.cible.email), str(b.etab.code), b.cible.prenom + " " + b.cible.nom]
    fautes = []
    for methode, gabarit in ROUTES_A_PARAMETRES:
        url = _url(gabarit, identifiants_b)
        reponse = _appeler(client_a, methode, url)
        corps = reponse.content.decode()
        if reponse.status_code != 404:
            fautes.append(f"{methode.upper()} {gabarit} -> {reponse.status_code} {corps[:120]}")
            continue
        if reponse.json().get("code") != "INTROUVABLE":
            fautes.append(f"{methode.upper()} {gabarit} -> 404 mais code {reponse.json()}")
        if any(s in corps for s in secrets_de_b):
            fautes.append(f"{methode.upper()} {gabarit} -> données de B dans la réponse")
    assert not fautes, "Fuites ou statuts inattendus :\n" + "\n".join(fautes)


def test_controle_les_lectures_de_ses_propres_objets_reussissent(mondes, client_a):
    """Contre-épreuve : la matrice ne réussit pas « à vide » (tout en 404)."""
    a, _ = mondes
    identifiants_a = a.identifiants()
    # Lectures seulement : les écritures déclencheraient de vrais effets (step-up, e-mails).
    lectures = [(m, c) for m, c in ROUTES_A_PARAMETRES if m == "get"]
    non_200 = [
        (m, c)
        for m, c in lectures
        if _appeler(client_a, m, _url(c, identifiants_a)).status_code != 200
    ]
    assert len(lectures) >= 3
    assert not non_200, f"Lectures de ses propres objets refusées : {non_200}"


# --- Routes sans paramètre : ni lecture ni écriture croisée -----------------------------------


def test_aucune_donnee_de_b_dans_les_lectures_de_a(mondes, client_a):
    """Chaque GET sans paramètre renvoie 200 sans jamais citer un identifiant ou un e-mail de B."""
    _, b = mondes
    marques = [str(v) for v in b.identifiants().values()] + [
        b.cible.email,
        b.org.awa.email,
        b.etab.code,
        str(b.etab.id),
    ]
    fautes = []
    for methode, chemin in ROUTES_SANS_PARAMETRE:
        if methode != "get" or chemin.endswith(".xlsx"):
            continue
        reponse = _appeler(client_a, "get", chemin)
        assert reponse.status_code in (200, 204), (
            chemin,
            reponse.status_code,
            reponse.content[:200],
        )
        corps = reponse.content.decode()
        fautes += [f"GET {chemin} cite {m}" for m in marques if m in corps]
    assert not fautes, "\n".join(fautes)


def test_export_audit_de_a_ne_contient_rien_de_b(mondes, client_a):
    _, b = mondes
    reponse = client_a.get("/api/v1/audit/export.xlsx")
    assert reponse.status_code == 200
    contenu = b"".join(reponse.streaming_content) if reponse.streaming else reponse.content
    assert b.etab.code.encode() not in contenu
    assert str(b.etab.id).encode() not in contenu


def test_creation_dans_a_ne_peut_pas_referencer_un_objet_de_b(mondes, client_a):
    """Les clés étrangères fournies par l'appelant (rôle, unité, utilisateur de B) sont rejetées."""
    _, b = mondes
    reponse = client_a.post(
        "/api/v1/admin/utilisateurs",
        {
            "email": "intrus@banque-a.test",
            "prenom": "In",
            "nom": "Trus",
            "affectations": [{"role_id": str(b.role_id), "unite_id": str(b.unite_id)}],
        },
        format="json",
    )
    assert reponse.status_code in (400, 404, 422), reponse.content[:300]
    assert str(b.role_id) not in reponse.content.decode()
    reponse = client_a.post(
        "/api/v1/moi/absences",
        {
            "debut": "2031-03-11T00:00:00+00:00",
            "fin": "2031-03-16T00:00:00+00:00",
            "motif": "CONGE",
            "delegataire_id": str(b.org.cheikh.pk),
        },
        format="json",
    )
    assert reponse.status_code in (400, 404, 409, 422), reponse.content[:300]
