import type { Page, Route } from "@playwright/test";
import { json } from "./aide";
import { MOI_COMPLET, moiAvec, ouvrirEtSimuler, page as pageDe } from "./donnees";
import type { Gestionnaire } from "./aide";

/** Données simulées de Mon compte (F6) et de l'administration (F7). */

export const MOI_ADMIN = moiAvec({
  modules: ["COMPTE", "ADMINISTRATION", "AUDIT"],
  permissions: ["admin.utilisateurs", "admin.roles", "admin.organisation", "admin.securite", "admin.absences", "audit.lecture", "audit.export"],
  role_principal: { id: "33333333-3333-4333-8333-333333333333", libelle: "Directeur administratif et financier", unite: "Direction administrative et financière" },
});

export const SECURITE = {
  authenticator: { statut: "ACTIVE", libelle: "Application d'authentification", active_le: "2026-09-12T09:00:00Z" },
  codes_secours_restants: 7,
  signature_bloquee: false,
  signalement: null,
  mdp_modifie_le: "2026-09-12T09:00:00Z",
  mot_de_passe_expire: false,
};

export const SESSIONS = [
  { id: "aaaaaaaa-0000-4000-8000-000000000001", appareil: "Chrome sur Windows", ip: "10.0.0.5", methode_mfa: "TOTP", cree_le: "2026-10-19T08:02:00Z", derniere_activite: "2026-10-19T09:10:00Z", courante: true },
  { id: "aaaaaaaa-0000-4000-8000-000000000002", appareil: "Safari sur iPhone", ip: "41.82.10.7", methode_mfa: "TOTP", cree_le: "2026-10-17T18:30:00Z", derniere_activite: "2026-10-18T07:45:00Z", courante: false },
];

export const PREFERENCES = { email: true, push: false, sms: false, resume_quotidien: true, heure_resume: "08:00" };

export const DELEGATAIRES = [
  { id: "bbbbbbbb-0000-4000-8000-000000000001", nom: "Fatou Sarr", role_principal: "Contrôleur de gestion", pouvoirs_suffisants: true },
  { id: "bbbbbbbb-0000-4000-8000-000000000002", nom: "Ousseynou Faye", role_principal: "Comptable fournisseurs", pouvoirs_suffisants: false },
];

export function absence(statut: string, extra: Record<string, unknown> = {}) {
  return {
    id: "cccccccc-0000-4000-8000-000000000001",
    demandeur: { id: "11111111-1111-4111-8111-111111111111", nom: "Abdou Kane" },
    debut: "2026-11-02T00:00:00Z",
    fin: "2026-11-06T23:59:00Z",
    motif: "CONGE",
    motif_libelle: "Congé",
    commentaire: "Congés annuels",
    statut,
    valideur: statut === "SOUMISE" ? null : { id: "dddddddd-0000-4000-8000-000000000001", nom: "Ibrahima Ndiaye" },
    decide_le: statut === "SOUMISE" ? null : "2026-10-19T09:00:00Z",
    motif_refus: "",
    cree_le: "2026-10-19T08:00:00Z",
    delegation: { id: "eeeeeeee-0000-4000-8000-000000000001", delegataire: { id: DELEGATAIRES[0]!.id, nom: "Fatou Sarr" }, role: null, debut: "2026-11-02T00:00:00Z", fin: "2026-11-06T23:59:00Z", statut: "EN_ATTENTE" },
    ...extra,
  };
}

export function notification(n: number, extra: Record<string, unknown> = {}): Record<string, unknown> & { titre: string; lue_le: string | null } {
  return {
    id: `ffffffff-0000-4000-8000-${String(n).padStart(12, "0")}`,
    type: "ABSENCE_A_VALIDER",
    titre: `Notification ${n}`,
    corps: `Texte de la notification ${n}`,
    lien: "/absences/cccccccc-0000-4000-8000-000000000001",
    lue_le: null,
    cree_le: "2026-10-19T08:30:00Z",
    ...extra,
  };
}

/** Gestionnaires communs de Mon compte : l'appelant complète ou remplace. */
export function gestionnairesCompte(extra: Record<string, Gestionnaire> = {}): Record<string, Gestionnaire> {
  return {
    "GET /moi/securite": (_a, route) => json(route, SECURITE),
    "GET /moi/sessions": (_a, route) => json(route, SESSIONS),
    "GET /moi/absences": (_a, route) => json(route, pageDe([])),
    "GET /moi/delegataires-possibles": (_a, route) => json(route, DELEGATAIRES),
    "GET /moi/delegations-recues": (_a, route) => json(route, []),
    "GET /moi/preferences-notification": (_a, route) => json(route, PREFERENCES),
    "GET /moi/notifications": (_a, route) => json(route, { ...pageDe([]), non_lues: 0 }),
    ...extra,
  };
}

export async function ouvrirCompte(page: Page, extra: Record<string, Gestionnaire> = {}, moi: unknown = MOI_COMPLET) {
  return ouvrirEtSimuler(page, moi, gestionnairesCompte(extra));
}

// --- Administration --------------------------------------------------------

export const ROLES = [
  { id: "r1", code: "administrateur-alpha", libelle: "Administrateur ALPHA", description: "Administre l'établissement", permissions: ["admin.utilisateurs", "admin.roles"], est_systeme: true, actif: true, ordre: 1, nb_titulaires: 1, vacant: false },
  { id: "r2", code: "daf", libelle: "DAF", description: "Directeur administratif et financier", permissions: ["audit.lecture"], est_systeme: false, actif: true, ordre: 2, nb_titulaires: 2, vacant: false },
  { id: "r3", code: "chef-de-service", libelle: "Chef de service", description: "", permissions: [], est_systeme: false, actif: true, ordre: 3, nb_titulaires: 0, vacant: true },
];

export const PERMISSIONS = [
  { code: "admin.utilisateurs", libelle: "Utilisateurs", description: "Inviter, modifier, suspendre, déverrouiller les utilisateurs" },
  { code: "admin.roles", libelle: "Rôles et habilitations", description: "Gérer le catalogue des rôles" },
  { code: "audit.lecture", libelle: "Journal d'audit (lecture)", description: "Consulter le journal d'audit" },
];

export function utilisateur(id: string, prenom: string, nom: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    prenom,
    nom,
    initiales: `${prenom[0]}${nom[0]}`,
    email: `${prenom[0]}.${nom}@etablissement-demo.sn`.toLowerCase(),
    role_principal: "DAF",
    perimetre: "Finances",
    authenticator: "ACTIVE",
    derniere_connexion: "2026-10-12T08:05:00Z",
    statut: "ACTIF",
    verrouille: false,
    ...extra,
  };
}

export const UTILISATEURS = [
  utilisateur("u1", "Ibrahima", "Ndiaye", { role_principal: "Administrateur ALPHA", perimetre: "Tout l'établissement" }),
  utilisateur("u2", "Fatou", "Sarr", { role_principal: "Contrôleur de gestion", perimetre: "Budget" }),
  utilisateur("u3", "Moussa", "Ndiaye", { role_principal: "Chef de service", perimetre: "Agence de Thiès", authenticator: "NON_CONFIGUREE", derniere_connexion: null, statut: "INVITE" }),
  utilisateur("u4", "Khady", "Mbaye", { statut: "ACTIF", verrouille: true }),
];

export function fiche(u: ReturnType<typeof utilisateur>, extra: Record<string, unknown> = {}) {
  return {
    ...u,
    telephone_mobile: "+221770000000",
    langue: "fr",
    responsable: null,
    echecs_connexion: 0,
    verrouille_jusqua: null,
    bloque_par_admin: false,
    mfa_a_reconfigurer: false,
    signature_bloquee: false,
    active_le: "2026-09-01T10:00:00Z",
    cree_le: "2026-08-25T10:00:00Z",
    affectations: [{ id: "af1", role: { id: "r1", libelle: u.role_principal ?? "DAF" }, unite: null, principal: true, debut: "2026-09-01", fin: null }],
    sessions_actives: [],
    signalement: null,
    ...extra,
  };
}

export function evenementAdmin(seq: number, extra: Record<string, unknown> = {}) {
  return {
    seq,
    horodatage: "2026-10-09T10:00:00Z",
    acteur_type: "UTILISATEUR",
    acteur_libelle: "Ibrahima Ndiaye",
    categorie: "ADMINISTRATION",
    action: "affectation.creee",
    action_libelle: "Attribution d'un rôle",
    objet_type: "organisation.affectationrole",
    objet_id: "x",
    objet_libelle: "Rôle « Responsable RH » attribué à Aminata Diallo",
    avant: null,
    apres: null,
    detail: "",
    ip: "10.0.0.1",
    hash: "a41f0000000000009c2e",
    hash_court: "a41f…9c2e",
    ...extra,
  };
}

export const PARAMETRES = {
  inactivite_session_min: 15,
  duree_max_session_h: 12,
  mdp_longueur_min: 12,
  mdp_historique: 5,
  mdp_expiration_jours: null,
  tentatives_max: 5,
  verrouillage_min: 15,
  verrouillages_max_24h: 3,
  validite_invitation_h: 72,
  validite_reinit_mdp_min: 30,
  retention_audit_annees: 10,
  email_controle_interne: "controle@etablissement-demo.sn",
  modules_actifs: ["COMPTE", "ADMINISTRATION", "AUDIT"],
  modifie_le: "2026-10-01T10:00:00Z",
};

export function signalement(id: string, statut: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    utilisateur: { id: "u2", nom: "Fatou Sarr", email: "f.sarr@etablissement-demo.sn" },
    canal: "MON_COMPTE",
    statut,
    signale_le: "2026-10-19T07:30:00Z",
    traite_par: null,
    mode_verification: null,
    reference_demande: null,
    commentaire: "",
    traite_le: null,
    ...extra,
  };
}

export function gestionnairesAdmin(extra: Record<string, Gestionnaire> = {}): Record<string, Gestionnaire> {
  return {
    "GET /admin/roles": (_a: unknown, route: Route) => json(route, ROLES),
    "GET /admin/unites": (_a: unknown, route: Route) => json(route, []),
    "GET /admin/permissions": (_a: unknown, route: Route) => json(route, PERMISSIONS),
    "GET /moi/notifications": (_a: unknown, route: Route) => json(route, { ...pageDe([]), non_lues: 0 }),
    ...extra,
  } as Record<string, Gestionnaire>;
}
