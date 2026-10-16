import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type VarianteBouton = "primaire" | "secondaire" | "validation" | "lien";
/** `normal` : 40 px, 14 px (écrans de l'application) ; `auth` : 44 px, 15 px. */
export type TailleBouton = "normal" | "auth";

const base =
  "cible-tactile inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-champ border font-semibold no-underline transition-colors duration-200 cursor-pointer disabled:cursor-not-allowed aria-disabled:cursor-not-allowed";

const variantes: Record<VarianteBouton, string> = {
  // .btn-p
  primaire:
    "border-transparent bg-encre text-white hover:bg-marque hover:text-white disabled:bg-desactive disabled:text-desactive-texte aria-disabled:bg-desactive aria-disabled:text-desactive-texte",
  // .btn-s
  secondaire:
    "bg-surface text-encre border-bordure-champ hover:bg-survol hover:text-encre disabled:bg-desactive disabled:text-desactive-texte disabled:border-transparent",
  // .btn-g
  validation:
    "border-transparent bg-succes text-white hover:bg-succes-survol hover:text-white disabled:bg-desactive disabled:text-desactive-texte",
  // lien d'action (ex. « Utiliser un code de secours »)
  lien: "border-transparent bg-transparent text-marque underline underline-offset-2 hover:text-encre px-1 disabled:text-desactive-texte",
};

const tailles: Record<TailleBouton, string> = {
  normal: "min-h-bouton px-4 text-[14px]",
  auth: "min-h-bouton-auth px-[18px] text-[15px]",
};

export function classesBouton(variante: VarianteBouton = "primaire", taille: TailleBouton = "normal", pleineLargeur = false) {
  return cn(base, variantes[variante], variante === "lien" ? "min-h-bouton text-[14px]" : tailles[taille], pleineLargeur && "w-full");
}

function Indicateur() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".3" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: VarianteBouton;
  taille?: TailleBouton;
  pleineLargeur?: boolean;
  /** Affiche un indicateur, désactive le bouton et pose `aria-busy`. */
  chargement?: boolean;
  icone?: ReactNode;
}

/** Bouton natif (`<button>`), `type="button"` par défaut. */
export function Button({
  variante = "primaire",
  taille = "normal",
  pleineLargeur,
  chargement = false,
  icone,
  type = "button",
  className,
  disabled,
  children,
  ...reste
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(classesBouton(variante, taille, pleineLargeur), className)}
      disabled={disabled || chargement}
      aria-busy={chargement || undefined}
      {...reste}
    >
      {chargement ? <Indicateur /> : icone}
      {children}
    </button>
  );
}

export interface LienBoutonProps extends ComponentProps<typeof Link> {
  variante?: VarianteBouton;
  taille?: TailleBouton;
  pleineLargeur?: boolean;
}

/** Lien de navigation avec l'apparence d'un bouton (`<a class="btn btn-p">` du prototype). */
export function LienBouton({ variante = "primaire", taille = "normal", pleineLargeur, className, ...reste }: LienBoutonProps) {
  return <Link className={cn(classesBouton(variante, taille, pleineLargeur), className)} {...reste} />;
}
