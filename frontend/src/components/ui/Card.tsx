import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /** Titre (h2, 17 px 600). */
  titre?: ReactNode;
  /** Niveau de titre, si la carte est imbriquée sous un h2. */
  niveauTitre?: 2 | 3;
  description?: ReactNode;
  /** Boutons à droite de l'en-tête. */
  actions?: ReactNode;
  /** `false` pour un contenu bord à bord (tableau). */
  marge?: boolean;
  as?: "section" | "div" | "article";
}

/** Carte (`.card` : fond blanc, bordure #E2E8F0, rayon 10 px). */
export function Card({ titre, niveauTitre = 2, description, actions, marge = true, as: Balise = "section", className, children, ...reste }: CardProps) {
  const Titre = niveauTitre === 2 ? "h2" : "h3";
  const entete = titre || description || actions;
  return (
    <Balise className={cn("min-w-0 rounded-carte border border-bordure bg-surface", className)} {...reste}>
      {entete && (
        <div className={cn("flex flex-wrap items-start justify-between gap-3 px-4.5 pt-4", !marge && "pb-3")}>
          <div className="flex min-w-0 flex-col gap-0.5">
            {titre && <Titre className="text-titre-carte text-encre">{titre}</Titre>}
            {description && <p className="text-[13px] text-texte-attenue">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn(marge && "px-4.5 pb-4.5", marge && (entete ? "pt-3.5" : "pt-4.5"))}>{children}</div>
    </Balise>
  );
}
