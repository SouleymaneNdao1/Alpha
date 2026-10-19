import type { Moi } from "@/lib/api/hooks/auth";

/**
 * Menu de la barre latérale, calculé depuis `Moi.modules` et `Moi.permissions`
 * (architecture § 7.2). Une entrée n'apparaît que si le module est actif ET si
 * la permission est détenue : un module sans permission (ou l'inverse) ne donne
 * jamais accès à l'écran.
 */
export type IconeMenu = "taches" | "administration" | "journal" | "compte";

export interface EntreeMenu {
  id: string;
  libelle: string;
  href: string;
  icone: IconeMenu;
  /** Préfixes de chemin pour lesquels l'entrée est active. */
  prefixes: string[];
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

export function construireMenu(moi: Moi): GroupeMenu[] {
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
          href: "/administration/utilisateurs",
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

export function entreeActive(entree: EntreeMenu, chemin: string): boolean {
  return entree.prefixes.some((p) => chemin === p || chemin.startsWith(`${p}/`));
}

/** `/administration/...` : route accessible à tout titulaire d'une permission `admin.*` (menu masqué sinon). */
export function peutAdministrer(moi: Moi): boolean {
  return moi.modules.includes("ADMINISTRATION") && possedeUnePermissionDe(moi, "admin.");
}
