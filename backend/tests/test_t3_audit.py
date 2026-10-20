"""T3 · Journal d'audit : compléments d'intégrité, de concurrence et de confidentialité.

Complète ``test_audit_base.py`` (triggers, RLS, 100 écritures concurrentes),
``test_audit_service.py``
et ``test_audit_verification.py`` (altérations) :

- contournements du propriétaire (rôle de réplication, désactivation des triggers par alpha_app) ;
- écritures concurrentes sur la chaîne plateforme, avec annulations et écritures hors transaction :
  ni trou ni fourche, chaînage recalculé INDÉPENDAMMENT du vérificateur ;
- fourche (deux événements de même rang) impossible, même propriétaire trigger coupé ;
- altérations plus fines détectées « au bon numéro » (chaînage, horodatage, déplacement d'un
  événement vers une autre chaîne, ajout d'un faux événement en fin de chaîne) ;
- aucun secret (mot de passe, secret TOTP, code de secours, jeton, cookie de session) ni dans le
  journal d'audit, ni dans les logs, à travers les parcours sensibles.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core import mail
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import Client

from alpha.audit import canonique
from alpha.audit.models import Categorie, StatutControle
from alpha.audit.services import journaliser
from alpha.audit.verification import lancer_verification
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from tests.bd import ALIAS_APP, ALIAS_PROPRIETAIRE, BASES_PROPRIETAIRE, sql

pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_PROPRIETAIRE)

ZERO = "0" * 64


def _refuse(alias: str, requete: str, *, motif: str) -> None:
    with pytest.raises(DatabaseError, match=motif), transaction.atomic(using=alias):
        sql(alias, requete)


def _chaine(etablissement_id) -> list[tuple]:
    """(seq, hash_precedent, hash, payload_canonique) de la chaîne, lus hors RLS."""
    with transaction.atomic(using=ALIAS_PROPRIETAIRE):
        if etablissement_id is None:
            ou, params = "etablissement_id IS NULL", []
        else:
            ou, params = "etablissement_id = %s", [str(etablissement_id)]
        return sql(
            ALIAS_PROPRIETAIRE,
            "SELECT seq, hash_precedent, hash, payload_canonique FROM evenement_audit "  # noqa: S608
            f"WHERE {ou} ORDER BY seq",
            params,
        )


def _verifier_independamment(lignes: list[tuple], etablissement_id) -> None:
    """Rang contigu 1..N, chaînage hash_precedent = hash précédent, empreinte recalculée."""
    assert [seq for seq, *_ in lignes] == list(range(1, len(lignes) + 1)), "trou ou doublon de rang"
    precedent = canonique.genese(etablissement_id)
    for seq, hash_precedent, hash_, payload in lignes:
        assert hash_precedent == precedent, f"chaînage rompu au rang {seq}"
        assert hash_ == canonique.empreinte(hash_precedent, seq, payload), f"empreinte, rang {seq}"
        precedent = hash_


# --- Contournements du propriétaire -----------------------------------------------------------


def _un_evenement(etab) -> int:
    with contexte_tenant(etab.id, using=ALIAS_APP):
        journaliser("test.t3.un", Categorie.SECURITE, detail="original", using=ALIAS_APP)
    return 1


def test_le_role_de_replication_ne_desactive_pas_le_trigger(etab_a):
    """``session_replication_role = replica`` coupe les triggers ordinaires : le propriétaire ne
    doit ni pouvoir le poser, ni modifier le journal une fois posé."""
    _un_evenement(etab_a)
    try:
        with transaction.atomic(using=ALIAS_PROPRIETAIRE):
            sql(ALIAS_PROPRIETAIRE, "SET LOCAL session_replication_role = replica")
            sql(ALIAS_PROPRIETAIRE, "UPDATE evenement_audit SET detail = 'falsifié'")
    except DatabaseError:
        pass  # refus franc (non super-utilisateur) ou trigger toujours actif : attendu
    (detail,) = {d for (d,) in sql(ALIAS_PROPRIETAIRE, "SELECT detail FROM evenement_audit")}
    assert detail == "original"


@pytest.mark.parametrize(
    "requete",
    [
        "ALTER TABLE evenement_audit DISABLE TRIGGER evenement_audit_sans_maj",
        "ALTER TABLE evenement_audit DISABLE TRIGGER ALL",
        "DROP TRIGGER evenement_audit_sans_maj ON evenement_audit",
        "DROP TRIGGER evenement_audit_chainer ON evenement_audit",
        "ALTER TABLE evenement_audit NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE evenement_audit DISABLE ROW LEVEL SECURITY",
        "DROP POLICY audit_lecture ON evenement_audit",
        "DROP TABLE evenement_audit",
        "SET session_replication_role = replica",
    ],
)
def test_le_role_applicatif_ne_peut_ni_couper_un_trigger_ni_la_rls(etab_a, requete):
    _un_evenement(etab_a)
    with pytest.raises(DatabaseError), transaction.atomic(using=ALIAS_APP):
        sql(ALIAS_APP, requete)
    # Rien n'a bougé : triggers présents et actifs.
    etat = dict(
        sql(
            ALIAS_PROPRIETAIRE,
            "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'evenement_audit'::regclass "
            "AND NOT tgisinternal",
        )
    )
    assert etat.get("evenement_audit_sans_maj") == "O"
    assert etat.get("evenement_audit_chainer") == "O"
    assert etat.get("evenement_audit_sans_truncate") == "O"


def test_une_modification_a_zero_ligne_ne_laisse_aucune_trace_mais_ne_modifie_rien(etab_a):
    _un_evenement(etab_a)
    with transaction.atomic(using=ALIAS_PROPRIETAIRE):
        sql(ALIAS_PROPRIETAIRE, "UPDATE evenement_audit SET detail = 'x' WHERE false")
    assert sql(ALIAS_PROPRIETAIRE, "SELECT detail FROM evenement_audit") == [("original",)]


# --- Fourche impossible -----------------------------------------------------------------------


def _sans_trigger(trigger: str, travail) -> None:
    """Exécute ``travail`` avec ``trigger`` coupé par le propriétaire, puis le remet en place.

    Trois transactions distinctes : PostgreSQL refuse d'ALTER TABLE tant que des événements
    de contraintes différées (clé étrangère) sont en attente dans la même transaction.
    """
    with transaction.atomic(using=ALIAS_PROPRIETAIRE):
        sql(ALIAS_PROPRIETAIRE, f"ALTER TABLE evenement_audit DISABLE TRIGGER {trigger}")
    try:
        with transaction.atomic(using=ALIAS_PROPRIETAIRE):
            travail()
    finally:
        with transaction.atomic(using=ALIAS_PROPRIETAIRE):
            sql(ALIAS_PROPRIETAIRE, f"ALTER TABLE evenement_audit ENABLE TRIGGER {trigger}")


def _faux_evenement(etablissement_id, seq: int, hash_precedent: str, hash_: str) -> None:
    """Insertion brute par le propriétaire, trigger de chaînage coupé (attaquant interne)."""

    def inserer():
        sql(
            ALIAS_PROPRIETAIRE,
            "INSERT INTO evenement_audit (etablissement_id, horodatage, acteur_type, "
            "acteur_libelle, categorie, action, objet_type, objet_id, objet_libelle, detail, "
            "user_agent, payload_canonique, seq, hash_precedent, hash) "
            "VALUES (%s, now(), 'SYSTEME', 'faux', 'SECURITE', 'test.faux', '', '', '', '', '', "
            "'{}', %s, %s, %s)",
            [str(etablissement_id) if etablissement_id else None, seq, hash_precedent, hash_],
        )

    _sans_trigger("evenement_audit_chainer", inserer)


@pytest.mark.parametrize("plateforme", [False, True])
def test_deux_evenements_de_meme_rang_sont_refuses(etab_a, plateforme):
    """Une fourche (deux successeurs du rang 2) est refusée, même au propriétaire."""
    cible = None if plateforme else etab_a.id
    for i in range(3):
        if plateforme:
            with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, using=ALIAS_APP):
                journaliser(f"test.t3.{i}", Categorie.SECURITE, using=ALIAS_APP)
        else:
            with contexte_tenant(cible, using=ALIAS_APP):
                journaliser(f"test.t3.{i}", Categorie.SECURITE, using=ALIAS_APP)
    avant = _chaine(cible)
    with pytest.raises(IntegrityError):
        _faux_evenement(cible, 2, avant[0][2], ZERO)
    assert _chaine(cible) == avant


# --- Concurrence : pas de trou, pas de fourche ------------------------------------------------


class _Annulation(Exception):
    pass


def _travail(etablissement_id, numero: int, mode: str) -> None:
    """mode : « commit » (par défaut), « annule » (transaction annulée), « hors » (hors tx)."""
    try:
        if etablissement_id is None:
            cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, using=ALIAS_APP)
        else:
            cm = contexte_tenant(etablissement_id, using=ALIAS_APP)
        with cm:
            if mode == "annule":
                try:
                    with transaction.atomic(using=ALIAS_APP):
                        journaliser(f"test.t3.annule.{numero}", Categorie.SECURITE, using=ALIAS_APP)
                        raise _Annulation
                except _Annulation:
                    pass
            elif mode == "hors":
                journaliser(
                    f"test.t3.hors.{numero}",
                    Categorie.CONNEXION,
                    hors_transaction=True,
                    using=ALIAS_APP,
                )
            else:
                journaliser(f"test.t3.ok.{numero}", Categorie.SECURITE, using=ALIAS_APP)
    finally:
        connections[ALIAS_APP].close()
        connections["audit"].close()


MODES = ("commit", "annule", "hors", "commit")


@pytest.mark.django_db(transaction=True, databases=[*BASES_PROPRIETAIRE, "audit"])
def test_ecritures_concurrentes_plateforme_et_etablissement_sans_trou_ni_fourche(etab_a, etab_b):
    barriere = threading.Barrier(24)

    def lancer(cible, numero, mode):
        barriere.wait(timeout=30)
        _travail(cible, numero, mode)

    with ThreadPoolExecutor(max_workers=24) as executeur:
        travaux = []
        for i in range(48):
            cible = (None, etab_a.id, etab_b.id)[i % 3]
            travaux.append(executeur.submit(lancer, cible, i, MODES[i % len(MODES)]))
        for travail in travaux:
            travail.result(timeout=120)

    attendus = {None: 0, etab_a.id: 0, etab_b.id: 0}
    for i in range(48):
        if MODES[i % len(MODES)] != "annule":
            attendus[(None, etab_a.id, etab_b.id)[i % 3]] += 1
    for cible, nombre in attendus.items():
        lignes = _chaine(cible)
        assert len(lignes) == nombre, (cible, len(lignes), nombre)
        _verifier_independamment(lignes, cible)
        # Aucun événement d'une transaction annulée n'a laissé de trou.
        assert not any("annule" in p for *_, p in lignes)
        controle = lancer_verification(cible, using=ALIAS_APP)
        assert controle.statut == StatutControle.INTACTE, controle.message
        assert controle.dernier_seq == nombre


@pytest.mark.django_db(transaction=True, databases=[*BASES_PROPRIETAIRE, "audit"])
def test_evenements_hors_transaction_annulation_du_metier_sans_trou(etab_a):
    """Le refus d'authentification (hors transaction) survit à l'annulation du métier."""
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        journaliser("test.t3.avant", Categorie.SECURITE, using=ALIAS_APP)
    with (
        contexte_tenant(etab_a.id, using=ALIAS_APP),
        pytest.raises(_Annulation),
        transaction.atomic(using=ALIAS_APP),
    ):
        # Le refus (connexion indépendante) est écrit AVANT l'écriture métier de la transaction :
        # celle-ci tient le verrou de la chaîne jusqu'à son terme et le refus attendrait.
        journaliser("auth.connexion.echec", Categorie.CONNEXION, hors_transaction=True)
        journaliser("test.t3.metier", Categorie.SECURITE, using=ALIAS_APP)
        raise _Annulation
    with contexte_tenant(etab_a.id, using=ALIAS_APP):
        journaliser("test.t3.apres", Categorie.SECURITE, using=ALIAS_APP)
    lignes = _chaine(etab_a.id)
    _verifier_independamment(lignes, etab_a.id)
    actions = [
        a
        for (a,) in sql(
            ALIAS_PROPRIETAIRE,
            "SELECT action FROM evenement_audit WHERE etablissement_id = %s ORDER BY seq",
            [str(etab_a.id)],
        )
    ]
    assert actions == ["test.t3.avant", "auth.connexion.echec", "test.t3.apres"]


# --- Altérations détectées au bon numéro ------------------------------------------------------


def _ecrire(etablissement_id, n: int) -> None:
    with contexte_tenant(etablissement_id, using=ALIAS_APP):
        for i in range(n):
            journaliser(f"test.t3.e{i}", Categorie.MODIFICATION, detail=f"d{i}", using=ALIAS_APP)


def _alterer(requete: str, params=None) -> None:
    _sans_trigger("evenement_audit_sans_maj", lambda: sql(ALIAS_PROPRIETAIRE, requete, params))


def _verifier(etablissement_id):
    return lancer_verification(etablissement_id, using=ALIAS_APP)


def test_alteration_au_milieu_d_une_longue_chaine_signalee_au_bon_rang(etab_a):
    _ecrire(etab_a.id, 60)
    assert _verifier(etab_a.id).statut == StatutControle.INTACTE
    _alterer(
        "UPDATE evenement_audit SET objet_libelle = 'trafiqué' "
        "WHERE etablissement_id = %s AND seq = 37",
        [str(etab_a.id)],
    )
    controle = _verifier(etab_a.id)
    assert controle.statut == StatutControle.ROMPUE
    assert controle.premier_seq_invalide == 37
    assert controle.dernier_seq == 36


def test_alteration_du_chainage_hash_precedent(etab_a):
    _ecrire(etab_a.id, 6)
    _alterer(
        "UPDATE evenement_audit SET hash_precedent = repeat('a', 64) "
        "WHERE etablissement_id = %s AND seq = 4",
        [str(etab_a.id)],
    )
    controle = _verifier(etab_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 4)


def test_alteration_de_l_horodatage_ou_de_l_acteur(etab_a):
    _ecrire(etab_a.id, 5)
    _alterer(
        "UPDATE evenement_audit SET horodatage = horodatage - interval '1 day' "
        "WHERE etablissement_id = %s AND seq = 3",
        [str(etab_a.id)],
    )
    assert (_verifier(etab_a.id).premier_seq_invalide) == 3

    _alterer(
        "UPDATE evenement_audit SET acteur_libelle = 'Autre personne' "
        "WHERE etablissement_id = %s AND seq = 2",
        [str(etab_a.id)],
    )
    assert (_verifier(etab_a.id).premier_seq_invalide) == 2


def test_evenement_deplace_vers_une_autre_chaine_detecte_des_deux_cotes(etab_a, etab_b):
    _ecrire(etab_a.id, 5)
    _ecrire(etab_b.id, 5)
    _alterer(
        "UPDATE evenement_audit SET etablissement_id = %s, seq = 6 "
        "WHERE etablissement_id = %s AND seq = 3",
        [str(etab_b.id), str(etab_a.id)],
    )
    chez_a = _verifier(etab_a.id)
    assert (chez_a.statut, chez_a.premier_seq_invalide) == ("ROMPUE", 3)  # trou au rang 3
    chez_b = _verifier(etab_b.id)
    assert (chez_b.statut, chez_b.premier_seq_invalide) == ("ROMPUE", 6)  # événement étranger


def test_faux_evenement_ajoute_en_fin_de_chaine_detecte(etab_a):
    _ecrire(etab_a.id, 4)
    assert _verifier(etab_a.id).statut == StatutControle.INTACTE
    dernier = _chaine(etab_a.id)[-1]
    _faux_evenement(etab_a.id, 5, dernier[2], "f" * 64)  # empreinte non recalculée
    controle = _verifier(etab_a.id)
    assert (controle.statut, controle.premier_seq_invalide) == ("ROMPUE", 5)


def test_rupture_d_une_chaine_n_affecte_pas_les_autres(etab_a, etab_b):
    _ecrire(etab_a.id, 4)
    _ecrire(etab_b.id, 4)
    _alterer(
        "UPDATE evenement_audit SET detail = 'x' WHERE etablissement_id = %s AND seq = 2",
        [str(etab_a.id)],
    )
    assert _verifier(etab_a.id).statut == StatutControle.ROMPUE
    assert _verifier(etab_b.id).statut == StatutControle.INTACTE


# --- Aucun secret dans le journal ni dans les logs --------------------------------------------

MOT_DE_PASSE_ACTIVATION = "Tamarin-Gris-88#Qx"
MOT_DE_PASSE_RESET = "Fromager-Solide-93!z"
MOT_DE_PASSE_CHANGE = "Baobab-Sahel#42xw"
MOT_DE_PASSE_FAUX = "Faux-Mdp-Secret-77Y"


def _tous_les_evenements_en_texte() -> str:
    """Toutes les colonnes de toutes les lignes du journal (hors RLS), en JSON."""
    lignes = sql(ALIAS_PROPRIETAIRE, "SELECT row_to_json(e)::text FROM evenement_audit e")
    return "\n".join(ligne for (ligne,) in lignes)


def _jetons_des_emails() -> set[str]:
    trouves: set[str] = set()
    for message in mail.outbox:
        textes = [message.body] + [c for c, _ in getattr(message, "alternatives", [])]
        for texte in textes:
            trouves |= set(
                re.findall(r"(?:jeton=|reinitialisation/|reenrolement/)([\w\-]{20,})", texte)
            )
    return trouves


@pytest.mark.django_db(transaction=True, databases=[*BASES_PROPRIETAIRE, "audit"])
def test_aucun_secret_dans_le_journal_ni_les_logs_a_travers_les_parcours(
    etab_a, caplog, capfd, client_connecte
):
    from alpha.comptes.models import AuthenticatorTOTP, StatutAuthenticator
    from alpha.organisation.models import Role
    from tests.outils_admin import creer_admin
    from tests.outils_auth import (
        MDP,
        UA_CHROME_WIN,
        URL_CONNEXION,
        URL_MFA,
        contexte_de,
        creer_compte,
        poster,
    )
    from tests.outils_b6 import API_AUTH, code_precedent, lien_de, messages_pour, secret_de

    caplog.set_level(logging.DEBUG)
    secrets_vus: dict[str, str] = {}

    def noter(nom: str, valeur: str) -> None:
        assert valeur and len(valeur) >= 6, nom
        secrets_vus[nom] = valeur

    def liberer(compte) -> None:
        with contexte_de(compte.utilisateur):
            AuthenticatorTOTP.objects.filter(statut=StatutAuthenticator.ACTIF).update(
                dernier_pas=None
            )

    from alpha.organisation.roles_defaut import semer_roles_par_defaut

    with contexte_tenant(etab_a.id):
        semer_roles_par_defaut(etab_a)
    compte = creer_compte(etab_a, email="awa.diop@banque-a.test")
    noter("mdp_initial", MDP)
    noter("secret_totp", compte.secret)
    for i, code in enumerate(compte.codes):
        noter(f"code_secours_{i}", code)
        noter(f"code_secours_sans_tiret_{i}", code.replace("-", ""))

    # 1. Connexion : échec de mot de passe, mot de passe juste, code MFA faux, code de secours.
    client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)
    noter("mdp_faux", MOT_DE_PASSE_FAUX)
    poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MOT_DE_PASSE_FAUX})
    poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    poster(client, URL_MFA, {"code": "000000"})
    r = poster(client, URL_MFA, {"code_secours": compte.codes[0]})
    assert r.status_code == 200, r.content
    noter("cookie_session", client.cookies["alpha_sid"].value)

    # 2. Changement de mot de passe (step-up TOTP).
    noter("mdp_change", MOT_DE_PASSE_CHANGE)
    liberer(compte)
    r = poster(
        client,
        "/api/v1/moi/mot-de-passe",
        {
            "actuel": MDP,
            "nouveau": MOT_DE_PASSE_CHANGE,
            "confirmation": MOT_DE_PASSE_CHANGE,
            "code": compte.totp(),
        },
    )
    assert r.status_code == 204, r.content

    # 3. Régénération des codes de secours.
    liberer(compte)
    r = poster(client, "/api/v1/moi/codes-secours", {"code": compte.totp()})
    assert r.status_code == 200, r.content
    for i, code in enumerate(r.json()["codes_secours"]):
        noter(f"nouveau_code_secours_{i}", code)
        noter(f"nouveau_code_secours_sans_tiret_{i}", code.replace("-", ""))

    # 4. Changement d'Authenticator.
    liberer(compte)
    r = poster(client, "/api/v1/moi/authenticator/changement", {"code_actuel": compte.totp()})
    assert r.status_code == 200, r.content
    nouveau_secret = r.json()["secret_affichable"].replace(" ", "")
    noter("nouveau_secret_totp", nouveau_secret)
    import pyotp

    r = poster(
        client,
        "/api/v1/moi/authenticator/changement/confirmer",
        {"code_nouveau": pyotp.TOTP(nouveau_secret).now()},
    )
    assert r.status_code == 204, r.content

    # 5. Mot de passe oublié puis réinitialisation (jeton envoyé par e-mail).
    anonyme = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)
    mail.outbox.clear()
    r = poster(anonyme, f"{API_AUTH}/mot-de-passe/oubli", {"email": compte.email})
    assert r.status_code == 202
    (message,) = messages_pour(compte.email, "Réinitialisation")
    jeton_reinit = lien_de(message, "/reinitialisation/")
    noter("jeton_reinitialisation", jeton_reinit)
    noter("mdp_reinitialise", MOT_DE_PASSE_RESET)
    r = poster(
        anonyme,
        f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton_reinit}",
        {
            "mot_de_passe": MOT_DE_PASSE_RESET,
            "confirmation": MOT_DE_PASSE_RESET,
            "code": pyotp.TOTP(nouveau_secret).at(__import__("time").time() + 30),
        },
    )
    assert r.status_code == 204, r.content

    # 6. Invitation puis activation d'un nouveau compte.
    banque_admin = creer_admin(etab_a, email="abdou.kane@banque-a.test")
    admin_client = client_connecte(banque_admin)
    mail.outbox.clear()
    with contexte_tenant(etab_a.id):
        role_id = Role.objects.get(code="analyste-credit").id
    r = admin_client.post(
        "/api/v1/admin/utilisateurs",
        {
            "email": "cheikh@banque-a.test",
            "prenom": "Cheikh",
            "nom": "Badiane",
            "role_id": str(role_id),
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    (invitation,) = messages_pour("cheikh@banque-a.test", "Activez votre compte")
    jeton = lien_de(invitation, "/activation?jeton=")
    noter("jeton_invitation", jeton)
    nouveau = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)
    url = f"{API_AUTH}/activation/{jeton}"
    noter("mdp_activation", MOT_DE_PASSE_ACTIVATION)
    assert (
        poster(
            nouveau,
            f"{url}/mot-de-passe",
            {"mot_de_passe": MOT_DE_PASSE_ACTIVATION, "confirmation": MOT_DE_PASSE_ACTIVATION},
        ).status_code
        == 204
    )
    r = poster(nouveau, f"{url}/authenticator")
    assert r.status_code == 200
    secret_activation = secret_de(r)
    noter("secret_totp_activation", secret_activation)
    r = poster(
        nouveau, f"{url}/authenticator/confirmer", {"code": code_precedent(secret_activation)}
    )
    assert r.status_code == 200, r.content
    for i, code in enumerate(r.json()["codes_secours"]):
        noter(f"code_secours_activation_{i}", code)
    assert poster(nouveau, f"{url}/terminer", {"codes_conserves": True}).status_code == 200

    # 7. Reconnexion avec le mot de passe réinitialisé : session et cookie tournent.
    se_connecter_apres = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)
    poster(
        se_connecter_apres,
        URL_CONNEXION,
        {"email": compte.email, "mot_de_passe": MOT_DE_PASSE_RESET},
    )

    # Jetons réellement envoyés par e-mail (peuvent légitimement figurer dans le corps du mail).
    for i, jeton_mail in enumerate(sorted(_jetons_des_emails())):
        noter(f"jeton_email_{i}", jeton_mail)
    # Empreintes stockées (hachage du mot de passe, secret chiffré).
    with contexte_de(compte.utilisateur):
        from alpha.comptes.models import Utilisateur

        noter("hachage_mdp", Utilisateur.objects.get(pk=compte.utilisateur.pk).password)

    journal = _tous_les_evenements_en_texte()
    logs = caplog.text + capfd.readouterr().err
    assert journal.count("{") > 20  # le scan ne porte pas sur un journal vide
    fuites = [
        f"{nom} dans {ou}"
        for nom, valeur in secrets_vus.items()
        for ou, texte in (("l'audit", journal), ("les logs", logs))
        if valeur in texte
    ]
    assert not fuites, fuites
