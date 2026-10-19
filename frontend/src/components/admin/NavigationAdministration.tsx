"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useMoi } from "@/components/shell/ContexteMoi";
import { AccesRefuse, EnTetePage } from "@/components/shell/Etats";
import { pagesAdministration } from "@/lib/permissions";
import { cn } from "@/lib/cn";

/** Gabarit de `/administration/*` : titre, onglets (selon les permissions de Moi) puis la page. */
export function GabaritAdministration({ children }: { children: ReactNode }) {
  const moi = useMoi();
  const chemin = usePathname();
  const pages = pagesAdministration(moi);
  if (pages.length === 0) return <AccesRefuse />;

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre="Utilisateurs et rôles"
        sousTitre={`${moi.etablissement ? `${moi.etablissement.raison_sociale} · ` : ""}comptes, catalogue des rôles, habilitations, délégations de pouvoirs et paramètres de sécurité.`}
      />
      <nav aria-label="Administration" className="-mb-2 overflow-x-auto">
        <ul className="m-0 flex min-w-max list-none border-b border-bordure p-0">
          {pages.map((p) => {
            const actif = chemin === p.href || chemin.startsWith(`${p.href}/`);
            return (
              <li key={p.id}>
                <Link
                  href={p.href}
                  aria-current={actif ? "page" : undefined}
                  className={cn(
                    "cible-tactile -mb-px mr-[22px] inline-flex min-h-[42px] items-center whitespace-nowrap border-0 border-b-2 px-1 text-[14px] font-semibold no-underline",
                    actif ? "border-marque text-encre" : "border-transparent text-texte-attenue hover:text-encre",
                  )}
                >
                  {p.libelle}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {children}
    </div>
  );
}
