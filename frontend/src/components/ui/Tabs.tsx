"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface Onglet {
  id: string;
  libelle: ReactNode;
  /** Compteur affiché en pastille Mono (`.cnt` du prototype). */
  compteur?: number;
  contenu?: ReactNode;
  desactive?: boolean;
}

export interface TabsProps {
  onglets: readonly Onglet[];
  /** Nom accessible de la liste d'onglets (ex. « Mon compte »). */
  label: string;
  /** Onglet actif (mode contrôlé, ex. synchronisé avec `?onglet=`). */
  actif?: string;
  /** Onglet actif initial (mode non contrôlé). */
  actifInitial?: string;
  onChange?: (id: string) => void;
  /** `souligne` : onglets de page (`.tab`) ; `segmente` : sélecteur à deux ou trois choix (écran 01b). */
  variante?: "souligne" | "segmente";
  className?: string;
}

/**
 * Onglets accessibles (motif WAI-ARIA « Tabs », activation automatique) :
 * flèches gauche/droite, Début et Fin déplacent le focus et activent l'onglet ;
 * seul l'onglet actif est dans l'ordre de tabulation.
 */
export function Tabs({ onglets, label, actif, actifInitial, onChange, variante = "souligne", className }: TabsProps) {
  const base = useId();
  const [interne, setInterne] = useState(actifInitial ?? onglets[0]?.id);
  const courant = actif ?? interne;
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const actives = onglets.filter((o) => !o.desactive);

  const activer = (id: string) => {
    if (actif === undefined) setInterne(id);
    onChange?.(id);
    refs.current[id]?.focus();
  };

  const touche = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = actives.findIndex((o) => o.id === courant);
    const cible =
      e.key === "ArrowRight" ? actives[(i + 1) % actives.length]
      : e.key === "ArrowLeft" ? actives[(i - 1 + actives.length) % actives.length]
      : e.key === "Home" ? actives[0]
      : e.key === "End" ? actives[actives.length - 1]
      : undefined;
    if (cible) {
      e.preventDefault();
      activer(cible.id);
    }
  };

  const panneau = onglets.find((o) => o.id === courant);
  const segmente = variante === "segmente";

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={touche}
        className={cn(
          "flex",
          segmente ? "gap-1 rounded-champ bg-survol p-1" : "flex-wrap border-b border-bordure",
        )}
      >
        {onglets.map((o) => {
          const estActif = o.id === courant;
          return (
            <button
              key={o.id}
              ref={(el) => {
                refs.current[o.id] = el;
              }}
              type="button"
              role="tab"
              id={`${base}-onglet-${o.id}`}
              aria-selected={estActif}
              aria-controls={`${base}-panneau-${o.id}`}
              tabIndex={estActif ? 0 : -1}
              disabled={o.desactive}
              onClick={() => activer(o.id)}
              className={cn(
                "cible-tactile inline-flex cursor-pointer items-center justify-center gap-2 text-[14px] font-semibold disabled:cursor-not-allowed disabled:opacity-60",
                segmente
                  ? cn(
                      "min-h-bouton flex-1 basis-0 rounded-segment border-0 px-3",
                      estActif ? "bg-surface text-encre shadow-segment" : "bg-transparent text-texte-attenue hover:text-encre",
                    )
                  : cn(
                      // .tab / .tab-on
                      "-mb-px mr-[22px] min-h-[42px] border-0 border-b-2 bg-transparent px-1 last:mr-0",
                      estActif ? "border-marque text-encre" : "border-transparent text-texte-attenue hover:text-encre",
                    ),
              )}
            >
              {o.libelle}
              {o.compteur !== undefined && <Compteur valeur={o.compteur} />}
            </button>
          );
        })}
      </div>
      {onglets.map((o) =>
        o.contenu === undefined ? null : (
          <div
            key={o.id}
            role="tabpanel"
            id={`${base}-panneau-${o.id}`}
            aria-labelledby={`${base}-onglet-${o.id}`}
            hidden={o.id !== panneau?.id}
            tabIndex={0}
            className="pt-5 focus-visible:outline-offset-4"
          >
            {o.id === panneau?.id && o.contenu}
          </div>
        ),
      )}
    </div>
  );
}

/** Pastille de compteur (`.cnt` : Mono 600 12 px). */
export function Compteur({ valeur, className }: { valeur: number; className?: string }) {
  return (
    <span className={cn("rounded-pilule bg-bordure px-2 py-px font-mono text-[12px] font-semibold text-texte-2", className)}>
      {valeur}
    </span>
  );
}
