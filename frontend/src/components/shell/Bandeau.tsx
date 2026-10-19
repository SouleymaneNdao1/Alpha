"use client";

import type { Moi } from "@/lib/api/hooks/auth";
import { Cloche } from "./Cloche";

export interface BandeauProps {
  moi: Moi;
  onMenu: () => void;
  menuOuvert: boolean;
}

const classeBtn =
  "cible-tactile relative inline-flex h-10 min-w-10 items-center justify-center rounded-champ border border-bordure bg-surface px-2 text-texte-2 no-underline hover:bg-survol hover:text-encre";

/** Bandeau supérieur : menu (mobile), recherche (inactive au S1), établissement, cloche, aide. */
export function Bandeau({ moi, onMenu, menuOuvert }: BandeauProps) {
  return (
    <header className="flex flex-wrap items-center gap-2.5 border-b border-bordure pb-3">
      <button
        type="button"
        onClick={onMenu}
        aria-expanded={menuOuvert}
        aria-controls="menu-mobile"
        className={`${classeBtn} gap-2 px-3 text-[14px] font-semibold md:hidden`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
        Menu
      </button>

      <div className="relative min-w-0 flex-1 basis-[80px] md:basis-[200px] md:max-w-[420px]">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-3 text-texte-attenue"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-4-4" />
        </svg>
        <input
          type="search"
          aria-label="Rechercher"
          placeholder="Rechercher un dossier, un client, un NINEA…"
          disabled
          title="La recherche globale sera disponible prochainement."
          className="block h-10 w-full rounded-champ border border-bordure-champ bg-surface pl-9 pr-3 text-[14px] placeholder:text-texte-attenue disabled:cursor-not-allowed disabled:bg-survol"
        />
      </div>

      <span className="hidden flex-1 md:block" />

      {moi.etablissement && (
        <span className="hidden max-w-[240px] truncate rounded-pilule border border-bordure bg-surface px-3 py-1.5 text-[13px] text-texte-2 lg:inline-block">
          {moi.etablissement.raison_sociale}
        </span>
      )}

      {!moi.est_super_admin && <Cloche />}

      <span
        role="link"
        aria-disabled="true"
        aria-label="Aide en ligne"
        title="L'aide en ligne sera disponible prochainement."
        className={`${classeBtn} cursor-not-allowed font-semibold`}
      >
        ?
      </span>
    </header>
  );
}
