"""Données du jeu de démonstration (tâche B12) : de quoi reproduire les écrans du prototype.

Source : ``docs/sources/prototype.html`` (écrans « Utilisateurs et rôles », « À traiter » de la
banque et de la PME, « Mon compte »). Ce module ne contient QUE des données ; la logique est
dans ``alpha.plateforme.demo``.

- les noms, e-mails, rôles et services viennent du prototype ;
- trois comptes n'y figurent pas et sont inventés pour que le jeu soit complet : l'administrateur
  de la banque a le nom affiché dans l'historique du prototype (« Seynabou Diouf · Administrateur »)
  avec une adresse déduite du même modèle, et la directrice générale de la banque
  (« Directrice générale » sans nom dans le prototype) s'appelle ici Fatimata Sy ;
- les références de dossier des tâches fiscales, de contrat et de RH sont de la même forme que
  celles du prototype (le prototype n'en donne pas pour ces lignes).
"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.comptes.models import StatutUtilisateur
from alpha.organisation.models import TypeUnite
from alpha.taches.models import Action, Groupe, Module, TypeEcheance
from alpha.tenancy.models import TypeEtablissement

# --- Structures ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class UniteDemo:
    code: str
    libelle: str
    type: str
    parent: str | None = None  # code de l'unité parente ; None : directement sous la racine


@dataclass(frozen=True)
class UtilisateurDemo:
    cle: str  # partie locale de l'adresse e-mail (« a.kane »)
    prenom: str
    nom: str
    role: str  # code du rôle principal
    unite: str | None = None  # code de l'unité (None : tout l'établissement)
    responsable: str | None = None  # clé du responsable hiérarchique (défini avant)
    statut: str = StatutUtilisateur.ACTIF
    #: Habilitations supplémentaires (code du rôle, code de l'unité).
    en_plus: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class TacheDemo:
    cle: str
    module: str
    action: str
    reference: str
    titre: str
    urgence: str  # un ``Groupe`` : l'échéance est calculée pour tomber dans ce groupe
    sous_titre: str = ""
    montant: int | None = None
    type_echeance: str = TypeEcheance.AVANT
    #: Retard en jours (urgence EN_RETARD) ; sans effet pour les autres groupes.
    retard_jours: int = 1
    destinataire: str | None = None  # clé d'utilisateur
    role: str | None = None  # ou code de rôle (avec ``unite`` facultative)
    unite: str | None = None
    demandeur: str | None = None


@dataclass(frozen=True)
class AbsenceDemo:
    absent: str  # clé d'utilisateur
    delegataire: str  # clé d'utilisateur (reçoit une habilitation de suppléance, P5)
    duree_jours: int = 7
    commentaire: str = "Congé annuel (jeu de démonstration)"


@dataclass(frozen=True)
class EtablissementDemo:
    code: str
    raison_sociale: str
    type: str
    domaine: str  # domaine des adresses e-mail
    administrateur: str  # clé d'utilisateur invité par le provisionnement
    utilisateurs: tuple[UtilisateurDemo, ...]
    unites: tuple[UniteDemo, ...] = ()
    taches: tuple[TacheDemo, ...] = ()
    absence: AbsenceDemo | None = None
    #: Rôle à ajouter à l'administrateur, comme rôle principal (ex. DG et administrateur).
    administrateur_aussi: tuple[str, str | None] | None = None


SUPER_ADMIN_EMAIL = "superadmin@fyxop-demo.sn"
SUPER_ADMIN_PRENOM = "Super"
SUPER_ADMIN_NOM = "Admin FYXOP"
SUPER_ADMIN_ROLE = "Super-administrateur FYXOP"

# --- Établissement démo (banque) -----------------------------------------------------------------

_BANQUE_UNITES = (
    UniteDemo("direction-engagements", "Direction des engagements", TypeUnite.DIRECTION),
    UniteDemo("dakar-plateau", "Dakar-Plateau", TypeUnite.AGENCE),
    UniteDemo("agence-thies", "Agence Thiès", TypeUnite.AGENCE),
    UniteDemo("comite-credit", "Comité de crédit", TypeUnite.COMITE),
    UniteDemo(
        "direction-administrative-financiere",
        "Direction administrative et financière",
        TypeUnite.DIRECTION,
    ),
    UniteDemo(
        "comptabilite", "Comptabilité", TypeUnite.SERVICE, "direction-administrative-financiere"
    ),
    UniteDemo("ressources-humaines", "Ressources humaines", TypeUnite.SERVICE),
    UniteDemo("direction-juridique", "Direction juridique", TypeUnite.DIRECTION),
    UniteDemo("secretariat-general", "Secrétariat général", TypeUnite.SERVICE),
    UniteDemo("direction-logistique", "Direction logistique", TypeUnite.DIRECTION),
)

_BANQUE_UTILISATEURS = (
    UtilisateurDemo("s.diouf", "Seynabou", "Diouf", "administrateur-alpha"),
    UtilisateurDemo("f.sy", "Fatimata", "Sy", "directeur-general"),
    UtilisateurDemo(
        "m.sow", "Mamadou", "Sow", "responsable-credit", "direction-engagements", "f.sy"
    ),
    UtilisateurDemo("a.diop", "Awa", "Diop", "analyste-credit", "dakar-plateau", "m.sow"),
    UtilisateurDemo("k.seck", "Khady", "Seck", "analyste-credit", "dakar-plateau", "m.sow"),
    UtilisateurDemo("i.diallo", "Ibou", "Diallo", "agent-saisie", "dakar-plateau", "m.sow"),
    UtilisateurDemo("a.niang", "Aïssatou", "Niang", "membre-comite", "comite-credit"),
    UtilisateurDemo("o.gueye", "Ousmane", "Gueye", "auditeur-interne"),
    UtilisateurDemo(
        "c.badiane",
        "Cheikh",
        "Badiane",
        "analyste-credit",
        "agence-thies",
        "m.sow",
        statut=StatutUtilisateur.INVITE,
    ),
    UtilisateurDemo(
        "r.thiam",
        "Rokhaya",
        "Thiam",
        "agent-saisie",
        "agence-thies",
        "m.sow",
        statut=StatutUtilisateur.SUSPENDU,
    ),
    UtilisateurDemo(
        "a.kane", "Abdou", "Kane", "daf", "direction-administrative-financiere", "f.sy"
    ),
    UtilisateurDemo("a.diallo", "Aminata", "Diallo", "responsable-rh", "ressources-humaines"),
    UtilisateurDemo("m.fall", "Moustapha", "Fall", "juriste", "direction-juridique"),
    UtilisateurDemo("k.mbaye", "Khady", "Mbaye", "secretaire-conseil", "secretariat-general"),
    UtilisateurDemo(
        "o.faye",
        "Ousseynou",
        "Faye",
        "comptable",
        "comptabilite",
        "a.kane",
        # Suppléant du DAF : la délégation exige des pouvoirs au moins égaux (décision P5).
        en_plus=(("daf", "direction-administrative-financiere"),),
    ),
    UtilisateurDemo(
        "b.diouf", "Babacar", "Diouf", "chef-service", "direction-logistique", "a.kane"
    ),
)

_BANQUE_TACHES = (
    # Boîte « À traiter » du DAF (écran du prototype : 9 tâches, 4 groupes).
    TacheDemo(
        "ed-0077",
        Module.INTERNE,
        Action.DECIDER,
        "ED-2026-0077",
        "40 postes informatiques",
        Groupe.EN_RETARD,
        "14 600 000 FCFA · demandé par Babacar Diouf",
        14_600_000,
        retard_jours=1,
        destinataire="a.kane",
        demandeur="b.diouf",
    ),
    TacheDemo(
        "pay-0412",
        Module.TRESORERIE,
        Action.SIGNER,
        "PAY-2026-0412",
        "Lot de paiement fournisseurs, 6 factures",
        Groupe.AUJOURDHUI,
        "21 400 000 FCFA · votre signature est attendue",
        21_400_000,
        TypeEcheance.EXECUTION,
        destinataire="a.kane",
    ),
    TacheDemo(
        "tva-sept",
        Module.FISCAL,
        Action.VALIDER,
        "FIS-2026-0009",
        "TVA de septembre 2026",
        Groupe.AUJOURDHUI,
        "Préparée par la comptabilité · validation du DAF",
        None,
        TypeEcheance.ECHEANCE,
        destinataire="a.kane",
        demandeur="o.faye",
    ),
    TacheDemo(
        "retenues-sept",
        Module.FISCAL,
        Action.VALIDER,
        "FIS-2026-0010",
        "Retenues sur salaires · septembre",
        Groupe.AUJOURDHUI,
        "Préparées par la comptabilité · validation du DAF",
        None,
        TypeEcheance.ECHEANCE,
        destinataire="a.kane",
        demandeur="o.faye",
    ),
    TacheDemo(
        "dg-0019",
        Module.INTERNE,
        Action.DECIDER,
        "DG-2026-0019",
        "Dérogation de taux",
        Groupe.CETTE_SEMAINE,
        "Kër Transport · 7,9 % au lieu de 8,5 %",
        None,
        destinataire="a.kane",
    ),
    TacheDemo(
        "pp-0008",
        Module.INTERNE,
        Action.DECIDER,
        "PP-2026-0008",
        "Prêt logement au personnel",
        Groupe.CETTE_SEMAINE,
        "9 000 000 FCFA · avis du responsable crédit favorable",
        9_000_000,
        destinataire="a.kane",
    ),
    TacheDemo(
        "rh-avance",
        Module.RH,
        Action.DECIDER,
        "RH-2026-0031",
        "Avance sur salaire · Ibou Diallo",
        Groupe.CETTE_SEMAINE,
        "200 000 FCFA sur 2 mois · au-delà du seuil RH",
        200_000,
        destinataire="a.kane",
        demandeur="a.diallo",
    ),
    TacheDemo(
        "ctr-maintenance",
        Module.CONTRATS,
        Action.DECIDER,
        "CTR-2026-0014",
        "Maintenance informatique · échéance",
        Groupe.PLUS_TARD,
        "Renouveler, renégocier ou résilier",
        None,
        TypeEcheance.PREAVIS,
        destinataire="a.kane",
        demandeur="m.fall",
    ),
    TacheDemo(
        "ctr-bail-thies",
        Module.CONTRATS,
        Action.DECIDER,
        "CTR-2026-0009",
        "Bail de l'agence de Thiès · échéance",
        Groupe.PLUS_TARD,
        "Renouveler, renégocier ou résilier",
        None,
        TypeEcheance.PREAVIS,
        destinataire="a.kane",
        demandeur="m.fall",
    ),
    # File de traitement de l'analyste crédit (tableau de bord crédit du prototype).
    TacheDemo(
        "cr-0412",
        Module.CREDIT,
        Action.TRAITER,
        "CR-2026-0412",
        "Moussa Fall · crédit particulier",
        Groupe.EN_RETARD,
        "Étape Analyse · délai dépassé de 2 jours",
        12_500_000,
        retard_jours=2,
        destinataire="a.diop",
    ),
    TacheDemo(
        "cr-0418",
        Module.CREDIT,
        Action.COMPLETER,
        "CR-2026-0418",
        "SENAGRI SARL · crédit PME",
        Groupe.EN_RETARD,
        "Étape Complétude · bilan 2025 manquant",
        85_000_000,
        retard_jours=1,
        destinataire="a.diop",
    ),
    TacheDemo(
        "cr-0421",
        Module.CREDIT,
        Action.TRAITER,
        "CR-2026-0421",
        "Fatou Ndiaye · crédit particulier",
        Groupe.CETTE_SEMAINE,
        "Étape Scoring",
        6_000_000,
        destinataire="a.diop",
    ),
    # Tâche adressée à un RÔLE : visible de toutes les analystes (Awa Diop et Khady Seck).
    TacheDemo(
        "cr-0425",
        Module.CREDIT,
        Action.TRAITER,
        "CR-2026-0425",
        "Batiplus SA · crédit PME",
        Groupe.PLUS_TARD,
        "Étape Analyse · file commune des analystes",
        150_000_000,
        role="analyste-credit",
    ),
    TacheDemo(
        "comite-1015",
        Module.CREDIT,
        Action.DECIDER,
        "CC-2026-0011",
        "Comité de crédit · 4 dossiers inscrits",
        Groupe.CETTE_SEMAINE,
        "Séance du jeudi à 10:00",
        None,
        destinataire="a.niang",
    ),
)

BANQUE = EtablissementDemo(
    code="etablissement-demo",
    raison_sociale="Établissement démo",
    type=TypeEtablissement.BANQUE,
    domaine="etablissement-demo.sn",
    administrateur="s.diouf",
    utilisateurs=_BANQUE_UTILISATEURS,
    unites=_BANQUE_UNITES,
    taches=_BANQUE_TACHES,
    absence=AbsenceDemo(absent="a.kane", delegataire="o.faye"),
)

# --- Sahel Distribution (PME) --------------------------------------------------------------------

_PME_UNITES = (
    UniteDemo("finances", "Finances", TypeUnite.DIRECTION),
    UniteDemo("budget", "Budget", TypeUnite.SERVICE, "finances"),
    UniteDemo("comptabilite", "Comptabilité", TypeUnite.SERVICE, "finances"),
    UniteDemo("achats", "Achats", TypeUnite.SERVICE),
    UniteDemo("commercial", "Commercial", TypeUnite.DIRECTION),
    UniteDemo("ressources-humaines", "Ressources humaines", TypeUnite.SERVICE),
    UniteDemo("logistique", "Logistique", TypeUnite.SERVICE),
    UniteDemo("agence-thies", "Agence de Thiès", TypeUnite.AGENCE),
)

_PME_UTILISATEURS = (
    # Le directeur général est aussi l'administrateur de la plateforme pour sa société.
    UtilisateurDemo("i.ndiaye", "Ibrahima", "Ndiaye", "administrateur-alpha"),
    UtilisateurDemo("a.kane", "Abdou", "Kane", "daf", "finances", "i.ndiaye"),
    UtilisateurDemo("f.sarr", "Fatou", "Sarr", "controleur-gestion", "budget", "a.kane"),
    UtilisateurDemo(
        "o.faye", "Ousseynou", "Faye", "comptable-fournisseurs", "comptabilite", "a.kane"
    ),
    UtilisateurDemo("m.ba", "Mariama", "Ba", "responsable-achats", "achats", "i.ndiaye"),
    UtilisateurDemo("n.sarr", "Ndèye", "Sarr", "directrice-commerciale", "commercial", "i.ndiaye"),
    UtilisateurDemo("a.diallo", "Aminata", "Diallo", "responsable-rh", "ressources-humaines"),
    UtilisateurDemo("k.mbaye", "Khady", "Mbaye", "secretaire-conseil"),
    UtilisateurDemo("m.gaye", "Moustapha", "Gaye", "chef-service", "logistique", "i.ndiaye"),
    UtilisateurDemo(
        "m.ndiaye",
        "Moussa",
        "Ndiaye",
        "chef-service",
        "agence-thies",
        "i.ndiaye",
        statut=StatutUtilisateur.INVITE,
    ),
)

_PME_TACHES = (
    # Boîte « À traiter » du directeur général (écran du prototype : 6 tâches).
    TacheDemo(
        "fac-0918",
        Module.PME_FOURNISSEURS,
        Action.DECIDER,
        "FAC-0918",
        "Facture Sotiba Fournitures",
        Groupe.EN_RETARD,
        "Écart de 180 000 FCFA avec le bon de livraison : arbitrer",
        None,
        retard_jours=2,
        destinataire="i.ndiaye",
        demandeur="o.faye",
    ),
    TacheDemo(
        "pay-0412",
        Module.TRESORERIE,
        Action.SIGNER,
        "PAY-2026-0412",
        "Lot de paiement fournisseurs, 6 factures",
        Groupe.AUJOURDHUI,
        "8 740 000 FCFA · votre signature est attendue",
        8_740_000,
        TypeEcheance.EXECUTION,
        destinataire="i.ndiaye",
    ),
    TacheDemo(
        "ac-0233",
        Module.INTERNE,
        Action.DECIDER,
        "AC-2026-0233",
        "Chariot élévateur électrique",
        Groupe.AUJOURDHUI,
        "Validé par le contrôleur de gestion · votre décision",
        None,
        destinataire="i.ndiaye",
        demandeur="m.gaye",
    ),
    TacheDemo(
        "rh-essai",
        Module.RH,
        Action.DECIDER,
        "RH-2026-0042",
        "Fin de période d'essai · Aïda Faye",
        Groupe.CETTE_SEMAINE,
        "Confirmer, prolonger ou mettre fin à l'essai",
        None,
        destinataire="i.ndiaye",
        demandeur="a.diallo",
    ),
    TacheDemo(
        "ctr-exclusive",
        Module.CONTRATS,
        Action.TRAITER,
        "CTR-2026-0021",
        "Distribution exclusive · région Nord",
        Groupe.CETTE_SEMAINE,
        "En attente de l'avis de l'avocat, puis votre approbation",
        None,
        destinataire="i.ndiaye",
    ),
    TacheDemo(
        "conseil-1022",
        Module.GOUVERNANCE,
        Action.TRAITER,
        "GOV-2026-0006",
        "Conseil du 22/10 · 4 résolutions",
        Groupe.PLUS_TARD,
        "Envoyer la convocation et le dossier aux administrateurs",
        None,
        destinataire="i.ndiaye",
        demandeur="k.mbaye",
    ),
    # Quelques tâches des autres modules de la PME.
    TacheDemo(
        "bud-2026",
        Module.PME_BUDGET,
        Action.VALIDER,
        "BUD-2026-0005",
        "Révision du budget commercial T4",
        Groupe.CETTE_SEMAINE,
        "Proposée par la direction commerciale",
        None,
        destinataire="f.sarr",
        demandeur="n.sarr",
    ),
    TacheDemo(
        "cmd-nord",
        Module.PME_COMMERCIAL,
        Action.COMPLETER,
        "DC-2026-0118",
        "Offre Grande distribution du Nord",
        Groupe.PLUS_TARD,
        "Pièces commerciales à compléter",
        None,
        destinataire="n.sarr",
    ),
)

PME = EtablissementDemo(
    code="sahel-distribution",
    raison_sociale="Sahel Distribution",
    type=TypeEtablissement.PME,
    domaine="sahel-distribution.sn",
    administrateur="i.ndiaye",
    utilisateurs=_PME_UTILISATEURS,
    unites=_PME_UNITES,
    taches=_PME_TACHES,
    administrateur_aussi=("directeur-general", None),
)

ETABLISSEMENTS: tuple[EtablissementDemo, ...] = (BANQUE, PME)
