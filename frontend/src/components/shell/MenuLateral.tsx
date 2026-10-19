"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Compteur } from "@/components/ui";
import { useDeconnexion, type Moi } from "@/lib/api/hooks/auth";
import { cn } from "@/lib/cn";
import { construireMenu, entreeActive } from "@/lib/permissions";
import { IconeMenuSvg } from "./icones";

export interface MenuLateralProps {
  moi: Moi;
  /** Nombre de tâches à traiter, affiché sur « À traiter » (absent tant qu'inconnu). */
  compteurTaches?: number;
  /** Appelé après un clic sur un lien (fermeture du tiroir sur mobile). */
  onNavigation?: () => void;
}

const classeEntree =
  "relative flex min-h-[40px] items-center gap-2.5 rounded-champ px-3 py-2 text-[14px] font-medium no-underline transition-colors";

/** Contenu de la barre latérale (sombre) : logo, groupes, aide, pied utilisateur. */
export function MenuLateral({ moi, compteurTaches, onNavigation }: MenuLateralProps) {
  const chemin = usePathname();
  const router = useRouter();
  const deconnexion = useDeconnexion();
  const groupes = construireMenu(moi);
  const [ouvert, setOuvert] = useState(false);
  const pied = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ouvert) return;
    const fermer = (e: MouseEvent) => {
      if (pied.current && !pied.current.contains(e.target as Node)) setOuvert(false);
    };
    const echap = (e: KeyboardEvent) => e.key === "Escape" && setOuvert(false);
    document.addEventListener("mousedown", fermer);
    document.addEventListener("keydown", echap);
    return () => {
      document.removeEventListener("mousedown", fermer);
      document.removeEventListener("keydown", echap);
    };
  }, [ouvert]);

  return (
    <div className="flex min-h-full flex-col gap-4 bg-encre px-3 py-5 text-menu-texte">
      <div className="flex flex-col gap-0.5 px-3">
        <span className="font-mono text-[18px] font-semibold tracking-[.12em] text-accent">ALPHA</span>
        <span className="truncate text-[13px] text-texte-discret">{moi.etablissement?.raison_sociale ?? "Console FYXOP"}</span>
      </div>

      <nav aria-label="Navigation principale" className="flex flex-col gap-3">
        {groupes.map((g) => (
          <div key={g.titre} className="flex flex-col gap-0.5">
            <p className="m-0 px-3 pb-1 text-[11px] font-semibold uppercase tracking-[.08em] text-texte-discret">{g.titre}</p>
            {g.entrees.map((e) => {
              const active = entreeActive(e, chemin);
              return (
                <Link
                  key={e.id}
                  href={e.href}
                  onClick={onNavigation}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    classeEntree,
                    active ? "bg-marque text-white shadow-menu-actif hover:text-white" : "text-menu-texte hover:bg-menu-survol hover:text-white",
                  )}
                >
                  <IconeMenuSvg nom={e.icone} />
                  <span className="flex-1">{e.libelle}</span>
                  {e.id === "a-traiter" && compteurTaches !== undefined && compteurTaches > 0 && (
                    <Compteur valeur={compteurTaches} className="bg-menu-survol text-menu-texte" />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-2 border-t border-menu-survol pt-3.5">
        <span
          role="link"
          aria-disabled="true"
          title="L'aide en ligne sera disponible prochainement."
          className={cn(classeEntree, "cursor-not-allowed text-texte-discret")}
        >
          <IconeMenuSvg nom="aide" />
          <span>Aide en ligne</span>
        </span>
        <div ref={pied} className="relative">
          {ouvert && (
            <div role="menu" aria-label="Compte" className="absolute inset-x-0 bottom-full mb-2 rounded-carte border border-menu-survol bg-menu-survol p-1.5 shadow-flottante">
              <Link
                role="menuitem"
                href="/mon-compte"
                onClick={() => {
                  setOuvert(false);
                  onNavigation?.();
                }}
                className="flex min-h-[40px] items-center rounded-champ px-3 text-[14px] text-menu-texte no-underline hover:bg-encre hover:text-white"
              >
                Mon compte
              </Link>
              <button
                type="button"
                role="menuitem"
                disabled={deconnexion.isPending}
                onClick={() => deconnexion.mutate(undefined, { onSettled: () => router.replace("/connexion?motif=deconnexion") })}
                className="flex min-h-[40px] w-full cursor-pointer items-center rounded-champ border-0 bg-transparent px-3 text-left text-[14px] text-menu-texte hover:bg-encre hover:text-white"
              >
                Se déconnecter
              </button>
            </div>
          )}
          <button
            type="button"
            aria-expanded={ouvert}
            aria-haspopup="menu"
            onClick={() => setOuvert((o) => !o)}
            className="flex w-full cursor-pointer items-center gap-2.5 rounded-champ border-0 bg-transparent p-1.5 text-left hover:bg-menu-survol"
          >
            <span
              aria-hidden="true"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-marque font-mono text-[12px] font-semibold text-white"
            >
              {moi.initiales}
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13px] font-semibold text-white">
                {moi.prenom} {moi.nom}
              </span>
              <span className="truncate text-[12px] text-texte-discret">{moi.role_principal?.libelle ?? "Super-administrateur FYXOP"}</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
