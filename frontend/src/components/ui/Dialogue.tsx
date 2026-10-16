"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Base commune de Modal et Drawer : élément `<dialog>` natif ouvert avec
 * `showModal()`. Le navigateur fournit le piège de focus, l'inertie du reste
 * de la page, la touche Échap et `aria-modal`. On ajoute : fermeture au clic
 * sur le voile, blocage du défilement de la page, retour du focus à
 * l'élément d'origine.
 */
export interface DialogueProps {
  ouvert: boolean;
  onFermer: () => void;
  titre: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Boutons du pied (ex. « Annuler » / « Confirmer »). */
  pied?: ReactNode;
  /** `false` : Échap et le voile ne ferment pas (action en cours). */
  fermable?: boolean;
  /** Classe du `<dialog>` (positionnement et taille propres à Modal / Drawer). */
  classeDialogue: string;
  classeCorps?: string;
}

export function Dialogue({ ouvert, onFermer, titre, description, children, pied, fermable = true, classeDialogue, classeCorps }: DialogueProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const origine = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (ouvert && !d.open) {
      origine.current = document.activeElement as HTMLElement | null;
      d.showModal();
      const avant = document.documentElement.style.overflow;
      document.documentElement.style.overflow = "hidden";
      return () => {
        document.documentElement.style.overflow = avant;
        if (d.open) d.close();
        origine.current?.focus?.();
      };
    }
  }, [ouvert]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={`${id}-titre`}
      aria-describedby={description ? `${id}-description` : undefined}
      onCancel={(e) => {
        e.preventDefault();
        if (fermable) onFermer();
      }}
      onClick={(e) => {
        if (fermable && e.target === e.currentTarget) onFermer();
      }}
      className={cn(
        "flex-col overflow-hidden border border-bordure bg-surface p-0 text-encre shadow-flottante backdrop:bg-voile open:flex",
        classeDialogue,
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b border-bordure px-4.5 py-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={`${id}-titre`} className="text-titre-carte">
            {titre}
          </h2>
          {description && (
            <p id={`${id}-description`} className="text-[13px] text-texte-attenue">
              {description}
            </p>
          )}
        </div>
        {fermable && (
          <button
            type="button"
            onClick={onFermer}
            aria-label="Fermer"
            className="cible-tactile -mr-2 -mt-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-champ text-texte-attenue hover:bg-survol hover:text-encre"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        )}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-y-auto px-4.5 py-4", classeCorps)}>{children}</div>
      {pied && (
        <div className="flex flex-wrap justify-end gap-2.5 border-t border-bordure bg-entete-tableau px-4.5 py-3.5">{pied}</div>
      )}
    </dialog>
  );
}
