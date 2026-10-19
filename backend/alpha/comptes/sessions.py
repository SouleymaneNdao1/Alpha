"""Sessions par appareil (architecture § 4.2 étapes 11-12, § 4.6, § 4.8).

- ``creer_session_appareil`` : ligne ``session_appareil`` de la session Django courante ;
- ``etat_session`` : état de la session (cache Redis de 60 s, invalidé à chaque écriture) ;
- ``revoquer_session`` / ``revoquer_sessions`` : fin de session (motif ``MotifFinSession``),
  utilisables par la déconnexion, « Mon compte » (B9), l'administration (B7) et
  « téléphone perdu » (B6) ;
- ``connexion_inhabituelle`` : aucune session des 90 derniers jours avec la même
  famille de navigateur + OS ET le même préfixe IP (/16 en IPv4, /48 en IPv6).

Seule l'empreinte SHA-256 de la clé de session est stockée et utilisée comme clé
de cache : la clé de session elle-même n'est jamais journalisée.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import uuid
from dataclasses import dataclass

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from user_agents import parse as analyser_user_agent

from .models import MethodeMfa, MotifFinSession, SessionAppareil, Utilisateur

DUREE_CACHE_S = 60
PREFIXE_CACHE = "sessapp"
FENETRE_HABITUDES = datetime.timedelta(days=90)
MAX_SESSIONS_COMPAREES = 200


def empreinte_cle_session(cle: str) -> str:
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def _cle_cache(cle_hash: str) -> str:
    return f"{PREFIXE_CACHE}:{cle_hash}"


def oublier(cle_hash: str) -> None:
    cache.delete(_cle_cache(cle_hash))


# --- Appareil -------------------------------------------------------------------------------


def familles(user_agent: str) -> tuple[str, str]:
    """(famille du navigateur, famille de l'OS) : « Chrome », « Windows »."""
    ua = analyser_user_agent(user_agent or "")
    return ua.browser.family or "Other", ua.os.family or "Other"


def libelle_appareil(user_agent: str) -> str:
    """« Chrome · Windows 10 » (120 caractères au plus)."""
    if not user_agent:
        return "Appareil inconnu"
    ua = analyser_user_agent(user_agent)
    systeme = f"{ua.os.family} {ua.os.version_string}".strip()
    return f"{ua.browser.family} · {systeme}"[:120]


def prefixe_reseau(ip: str | None) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    if not ip:
        return None
    try:
        adresse = ipaddress.ip_address(ip)
    except ValueError:
        return None
    longueur = 16 if adresse.version == 4 else 48
    return ipaddress.ip_network(f"{adresse}/{longueur}", strict=False)


def connexion_inhabituelle(utilisateur: Utilisateur, user_agent: str, ip: str | None) -> bool:
    """Vrai si aucune session récente ne ressemble à celle-ci (§ 4.2, étape 12).

    Une toute première session (aucune session enregistrée pour le compte, cas de
    l'activation) n'est pas signalée.
    """
    sessions = SessionAppareil.objects.filter(utilisateur_id=utilisateur.pk)
    if not sessions.exists():
        return False
    depuis = timezone.now() - FENETRE_HABITUDES
    cible_familles = familles(user_agent)
    cible_reseau = prefixe_reseau(ip)
    recentes = sessions.filter(cree_le__gte=depuis).order_by("-cree_le")[:MAX_SESSIONS_COMPAREES]
    for agent, adresse in recentes.values_list("user_agent", "ip"):
        if familles(agent) != cible_familles:
            continue
        reseau = prefixe_reseau(adresse)
        if reseau is not None and cible_reseau is not None and reseau == cible_reseau:
            return False
    return True


# --- Création, état, révocation ------------------------------------------------------------


@dataclass(frozen=True)
class EtatSession:
    id: uuid.UUID
    utilisateur_id: uuid.UUID
    revoquee: bool
    derniere_activite: datetime.datetime
    expire_le: datetime.datetime

    def en_cache(self) -> dict:
        return {
            "id": str(self.id),
            "utilisateur_id": str(self.utilisateur_id),
            "revoquee": self.revoquee,
            "derniere_activite": self.derniere_activite.isoformat(),
            "expire_le": self.expire_le.isoformat(),
        }

    @classmethod
    def depuis_cache(cls, donnees: dict) -> EtatSession:
        return cls(
            id=uuid.UUID(donnees["id"]),
            utilisateur_id=uuid.UUID(donnees["utilisateur_id"]),
            revoquee=bool(donnees["revoquee"]),
            derniere_activite=parse_datetime(donnees["derniere_activite"]),
            expire_le=parse_datetime(donnees["expire_le"]),
        )

    @classmethod
    def de(cls, session: SessionAppareil) -> EtatSession:
        return cls(
            id=session.id,
            utilisateur_id=session.utilisateur_id,
            revoquee=session.revoque_le is not None,
            derniere_activite=session.derniere_activite,
            expire_le=session.expire_le,
        )


def _memoriser(cle_hash: str, etat: EtatSession) -> None:
    cache.set(_cle_cache(cle_hash), etat.en_cache(), timeout=DUREE_CACHE_S)


def creer_session_appareil(
    utilisateur: Utilisateur,
    cle_session: str,
    *,
    methode_mfa: str,
    duree_max: datetime.timedelta,
    user_agent: str,
    ip: str | None,
) -> SessionAppareil:
    if methode_mfa not in MethodeMfa.values:
        raise ValueError(f"Méthode MFA inconnue : {methode_mfa!r}.")
    maintenant = timezone.now()
    cle_hash = empreinte_cle_session(cle_session)
    session = SessionAppareil.objects.create(
        utilisateur=utilisateur,
        etablissement_id=utilisateur.etablissement_id,
        cle_session_hash=cle_hash,
        appareil=libelle_appareil(user_agent),
        user_agent=user_agent or "",
        ip=ip,
        methode_mfa=methode_mfa,
        cree_le=maintenant,
        derniere_activite=maintenant,
        expire_le=maintenant + duree_max,
    )
    _memoriser(cle_hash, EtatSession.de(session))
    return session


def etat_session(cle_session: str) -> EtatSession | None:
    """État de la session d'appareil liée à la clé de session Django (ou None)."""
    cle_hash = empreinte_cle_session(cle_session)
    donnees = cache.get(_cle_cache(cle_hash))
    if donnees is not None:
        return EtatSession.depuis_cache(donnees)
    session = SessionAppareil.objects.filter(cle_session_hash=cle_hash).first()
    if session is None:
        return None
    etat = EtatSession.de(session)
    _memoriser(cle_hash, etat)
    return etat


def noter_activite(cle_session: str, etat: EtatSession) -> None:
    """Met à jour ``derniere_activite`` (l'appelant limite à une écriture par minute)."""
    maintenant = timezone.now()
    SessionAppareil.objects.filter(id=etat.id, revoque_le__isnull=True).update(
        derniere_activite=maintenant
    )
    _memoriser(
        empreinte_cle_session(cle_session),
        EtatSession(etat.id, etat.utilisateur_id, False, maintenant, etat.expire_le),
    )


def revoquer_session(session: SessionAppareil, motif: str) -> bool:
    """Révoque une session d'appareil ; faux si elle l'était déjà."""
    if motif not in MotifFinSession.values:
        raise ValueError(f"Motif de fin de session inconnu : {motif!r}.")
    oublier(session.cle_session_hash)
    if session.revoque_le is not None:
        return False
    session.revoque_le = timezone.now()
    session.motif_fin = motif
    session.save(update_fields=["revoque_le", "motif_fin"])
    return True


def revoquer_sessions(
    utilisateur: Utilisateur, motif: str, *, sauf: uuid.UUID | None = None
) -> int:
    """Révoque toutes les sessions actives de l'utilisateur (sauf, éventuellement, une)."""
    actives = SessionAppareil.objects.filter(utilisateur_id=utilisateur.pk, revoque_le__isnull=True)
    if sauf is not None:
        actives = actives.exclude(id=sauf)
    nombre = 0
    for session in actives.select_for_update():
        nombre += int(revoquer_session(session, motif))
    return nombre


def session_par_cle(cle_session: str) -> SessionAppareil | None:
    return SessionAppareil.objects.filter(
        cle_session_hash=empreinte_cle_session(cle_session)
    ).first()
