import type { Moi } from "@/lib/api/hooks/auth";

/**
 * Menu de la barre latérale, calculé depuis `Moi.modules` et `Moi.permissions`
 * (architecture § 7.2). Une entrée n'apparaît que si le module est actif ET si
 * la permission est détenue : un module sans permission (ou l'inverse) ne donne
 * jamais accès à l'écran.
 */
export type IconeMenu = "taches" | "administration" | "journal" | "compte" | "etablissements";

export interface EntreeMenu {
  id: string;
  libelle: string;
  href: string;
  icone: IconeMenu;
  /** Préfixes de chemin pour lesquels l'entrée est active. */
  prefixes: string[];
  /** Préfixes qui désactivent l'entrée (ex. « /console » ne doit pas rester actif sur « /console/journal »). */
  exclus?: string[];
}

export interface GroupeMenu {
  titre: string;
  entrees: EntreeMenu[];
}

export function possede(moi: Pick<Moi, "permissions">, code: string): boolean {
  return moi.permissions.includes(code);
}

export function possedeUnePermissionDe(moi: Pick<Moi, "permissions">, prefixe: string): boolean {
  return moi.permissions.some((p) => p.startsWith(prefixe));
}

export interface PageAdministration {
  id: "utilisateurs" | "roles" | "habilitations" | "delegations" | "organisation" | "securite";
  libelle: string;
  href: string;
}

/**
 * Pages de `/administration/*` accessibles à l'utilisateur (onglets de l'écran 12). Les lectures
 * du catalogue des rôles et des unités sont ouvertes à `admin.utilisateurs` (invitation) ;
 * l'écriture exige `admin.roles` / `admin.organisation`. Les signalements « téléphone perdu »
 * relèvent de `admin.utilisateurs`, les paramètres de sécurité de `admin.securite`.
 */
export function pagesAdministration(moi: Pick<Moi, "permissions">): PageAdministration[] {
  const a = (...codes: string[]) => codes.some((c) => possede(moi, c));
  const pages: Array<PageAdministration & { visible: boolean }> = [
    { id: "utilisateurs", libelle: "Utilisateurs", href: "/administration/utilisateurs", visible: a("admin.utilisateurs") },
    { id: "roles", libelle: "Catalogue des rôles", href: "/administration/roles", visible: a("admin.roles", "admin.utilisateurs") },
    { id: "habilitations", libelle: "Rôles et habilitations", href: "/administration/habilitations", visible: a("admin.roles") },
    { id: "delegations", libelle: "Délégations", href: "/administration/delegations", visible: a("admin.utilisateurs", "admin.absences") },
    { id: "organisation", libelle: "Unités et périmètres", href: "/administration/organisation", visible: a("admin.organisation", "admin.utilisateurs") },
    { id: "securite", libelle: "Sécurité", href: "/administration/securite", visible: a("admin.securite", "admin.utilisateurs") },
  ];
  return pages.filter((p) => p.visible).map(({ visible: _v, ...p }) => p);
}

export function construireMenu(moi: Moi): GroupeMenu[] {
  // Super-admin FYXOP : la console seulement (la déconnexion est dans le pied du menu).
  if (moi.est_super_admin) {
    return [
      {
        titre: "Console FYXOP",
        entrees: [
          { id: "console", libelle: "Établissements", href: "/console", icone: "etablissements", prefixes: ["/console"], exclus: ["/console/journal"] },
          { id: "console-journal", libelle: "Journal de la plateforme", href: "/console/journal", icone: "journal", prefixes: ["/console/journal"] },
        ],
      },
    ];
  }

  const groupes: GroupeMenu[] = [];

  // « À traiter » : accueil de tout utilisateur (un super-admin y trouve un message explicatif tant que F9 n'existe pas).
  groupes.push({
    titre: "Gestion interne",
    entrees: [{ id: "a-traiter", libelle: "À traiter", href: "/a-traiter", icone: "taches", prefixes: ["/a-traiter"] }],
  });

  if (moi.modules.includes("ADMINISTRATION") && possedeUnePermissionDe(moi, "admin.")) {
    groupes.push({
      titre: "Administration",
      entrees: [
        {
          id: "administration",
          libelle: "Administration",
          href: pagesAdministration(moi)[0]?.href ?? "/administration/utilisateurs",
          icone: "administration",
          prefixes: ["/administration"],
        },
      ],
    });
  }

  if (moi.modules.includes("AUDIT") && possede(moi, "audit.lecture")) {
    groupes.push({
      titre: "Suivi et traçabilité",
      entrees: [{ id: "journal", libelle: "Journal d'audit", href: "/journal", icone: "journal", prefixes: ["/journal"] }],
    });
  }

  if (moi.modules.includes("COMPTE")) {
    groupes.push({
      titre: "Moi",
      entrees: [{ id: "mon-compte", libelle: "Mon compte", href: "/mon-compte", icone: "compte", prefixes: ["/mon-compte", "/absences"] }],
    });
  }

  return groupes;
}

const sous = (chemin: string, p: string) => chemin === p || chemin.startsWith(`${p}/`);

export function entreeActive(entree: EntreeMenu, chemin: string): boolean {
  if (entree.exclus?.some((p) => sous(chemin, p))) return false;
  return entree.prefixes.some((p) => sous(chemin, p));
}

/** `/administration/...` : route accessible à tout titulaire d'une permission `admin.*` (menu masqué sinon). */
export function peutAdministrer(moi: Moi): boolean {
  return moi.modules.includes("ADMINISTRATION") && possedeUnePermissionDe(moi, "admin.");
}
