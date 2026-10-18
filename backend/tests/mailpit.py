"""Client Mailpit des tests d'e-mail (tâche T1 ; utilisé par B6 et T4).

- Sans rien demander, les e-mails vont au backend EN MÉMOIRE de Django et se relisent
  dans ``django.core.mail.outbox`` (``config.settings.test``) : suffisant pour la plupart
  des tests ;
- un test qui veut vérifier l'acheminement SMTP réel demande la fixture ``mailpit``
  (``tests/conftest.py``) : elle bascule ``EMAIL_BACKEND`` sur SMTP
  (``EMAIL_HOST``/``EMAIL_PORT``) et renvoie un ``ClientMailpit`` qui relit les messages
  par l'API HTTP de Mailpit (``ALPHA_MAILPIT_API``). **Si Mailpit ne répond pas** (poste
  sans docker, CI sans service mailpit), **le test est sauté** (skip) avec le motif.

    def test_invitation(mailpit, utilisateur_a):
        ...
        message = mailpit.attendre_message(destinataire=utilisateur_a.email)
        assert "Activez votre compte" in message.sujet

Mailpit est partagé (services compose, autres suites) : on cible les messages par
destinataire, avec des adresses propres au test, plutôt que de tout effacer.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Mailpit est local (ou sur le réseau compose) : jamais de proxy sortant.
_OUVREUR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class MailpitIndisponible(RuntimeError):
    """Mailpit ne répond pas (service absent ou URL erronée)."""


@dataclass(frozen=True)
class MessageMailpit:
    id: str
    sujet: str
    expediteur: str
    destinataires: list[str]
    texte: str = ""
    html: str = ""
    entetes: dict[str, Any] = field(default_factory=dict)


class ClientMailpit:
    """Accès à l'API v1 de Mailpit (``ALPHA_MAILPIT_API``, ex. http://mailpit:8025/api/v1)."""

    def __init__(
        self,
        url_api: str,
        utilisateur: str = "",
        mot_de_passe: str = "",
        delai: float = 5.0,
    ) -> None:
        self.url_api = url_api.rstrip("/")
        self.delai = delai
        self._entetes = {"Accept": "application/json"}
        if utilisateur:
            # Mailpit protégé par mot de passe en recette (décision P11).
            jeton = base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode()).decode()
            self._entetes["Authorization"] = f"Basic {jeton}"

    # --- Transport ----------------------------------------------------------------------

    def _appel(
        self, methode: str, chemin: str, parametres: dict | None = None, delai: float | None = None
    ) -> Any:
        url = f"{self.url_api}/{chemin.lstrip('/')}"
        if parametres:
            url = f"{url}?{urllib.parse.urlencode(parametres)}"
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"URL Mailpit invalide : {url!r}.")
        requete = urllib.request.Request(url, method=methode, headers=self._entetes)  # noqa: S310
        try:
            with _OUVREUR.open(requete, timeout=delai or self.delai) as reponse:
                corps = reponse.read()
        except (urllib.error.URLError, OSError) as exc:
            raise MailpitIndisponible(f"Mailpit injoignable ({self.url_api}) : {exc}") from exc
        return json.loads(corps) if corps.strip() else None

    def disponible(self) -> bool:
        """Mailpit répond-il ? (délai court : un test sauté ne doit pas ralentir la suite.)"""
        try:
            self._appel("GET", "info", delai=1.0)
        except MailpitIndisponible:
            return False
        return True

    # --- Lecture ------------------------------------------------------------------------

    def rechercher(self, requete: str) -> list[dict]:
        """Résumés des messages correspondant à une recherche Mailpit (``to:…``, ``subject:…``)."""
        return self._appel("GET", "search", {"query": requete, "limit": 200})["messages"]

    def messages_pour(self, destinataire: str) -> list[dict]:
        return self.rechercher(f'to:"{destinataire}"')

    def lire(self, identifiant: str) -> MessageMailpit:
        brut = self._appel("GET", f"message/{identifiant}")
        return MessageMailpit(
            id=brut["ID"],
            sujet=brut.get("Subject", ""),
            expediteur=(brut.get("From") or {}).get("Address", ""),
            destinataires=[d["Address"] for d in brut.get("To") or []],
            texte=brut.get("Text", ""),
            html=brut.get("HTML", ""),
            entetes=brut.get("Headers", {}) or {},
        )

    def attendre_message(
        self, *, destinataire: str, sujet: str | None = None, delai: float = 5.0
    ) -> MessageMailpit:
        """Dernier message reçu par ``destinataire`` (attente active : envoi SMTP asynchrone)."""
        requete = f'to:"{destinataire}"' + (f' subject:"{sujet}"' if sujet else "")
        echeance = time.monotonic() + delai
        while True:
            resultats = self.rechercher(requete)
            if resultats:
                return self.lire(resultats[0]["ID"])  # Mailpit trie du plus récent au plus ancien
            if time.monotonic() >= echeance:
                raise AssertionError(f"Aucun e-mail reçu par Mailpit pour {requete!r}.")
            time.sleep(0.1)

    # --- Nettoyage ----------------------------------------------------------------------

    def supprimer_pour(self, destinataire: str) -> None:
        """Efface les messages d'un destinataire (sans toucher à ceux des autres suites)."""
        self._appel("DELETE", "search", {"query": f'to:"{destinataire}"'})
