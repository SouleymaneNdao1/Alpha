"use client";

import { useId, type InputHTMLAttributes, type ReactNode, type Ref, type SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/** `normal` : 42 px, 14 px (application) ; `auth` : 44 px, 15 px (authentification). */
export type TailleChamp = "normal" | "auth";

const classesChamp = (taille: TailleChamp, invalide: boolean) =>
  cn(
    "block w-full rounded-champ border bg-surface text-encre placeholder:text-texte-attenue",
    "focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque",
    "disabled:cursor-not-allowed disabled:bg-survol disabled:text-texte-attenue read-only:bg-entete-tableau",
    taille === "auth" ? "h-champ-auth px-3.5 text-[15px]" : "h-champ px-3 text-[14px]",
    invalide ? "border-danger-texte" : "border-bordure-champ",
  );

interface ChampCommun {
  /** Libellé visible, relié au champ par `htmlFor`. */
  label: ReactNode;
  /** Texte d'aide sous le champ (relié par `aria-describedby`). */
  aide?: ReactNode;
  /** Message d'erreur : pose `aria-invalid` et s'affiche sous le champ. */
  erreur?: string;
  taille?: TailleChamp;
  /** Libellé masqué visuellement (reste lu par les lecteurs d'écran). */
  labelMasque?: boolean;
  classeConteneur?: string;
}

function Cadre({
  id,
  label,
  aide,
  erreur,
  taille = "normal",
  labelMasque,
  classeConteneur,
  required,
  children,
}: ChampCommun & { id: string; required?: boolean; children: ReactNode }) {
  return (
    <div className={cn("flex flex-col", taille === "auth" ? "gap-2" : "gap-1.5", classeConteneur)}>
      <label
        htmlFor={id}
        className={cn("font-semibold text-texte-2", taille === "auth" ? "text-[14px]" : "text-[13px]", labelMasque && "sr-only")}
      >
        {label}
        {required && (
          <span className="text-danger-texte" aria-hidden="true">
            {" "}
            *
          </span>
        )}
      </label>
      {children}
      {aide && !erreur && (
        <p id={`${id}-aide`} className="text-[13px] text-texte-attenue">
          {aide}
        </p>
      )}
      {erreur && (
        <p id={`${id}-erreur`} className="text-[13px] font-medium text-danger-texte">
          {erreur}
        </p>
      )}
    </div>
  );
}

function decrit(id: string, aide: unknown, erreur: unknown, existant?: string) {
  return cn(existant, erreur ? `${id}-erreur` : aide ? `${id}-aide` : undefined) || undefined;
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size">, ChampCommun {
  ref?: Ref<HTMLInputElement>;
}

/** Champ de saisie avec libellé, aide et erreur (compatible react-hook-form `register`). */
export function Input({ label, aide, erreur, taille = "normal", labelMasque, classeConteneur, id, className, ...reste }: InputProps) {
  const auto = useId();
  const idChamp = id ?? auto;
  return (
    <Cadre {...{ id: idChamp, label, aide, erreur, taille, labelMasque, classeConteneur, required: reste.required }}>
      <input
        {...reste}
        id={idChamp}
        className={cn(classesChamp(taille, !!erreur), className)}
        aria-invalid={erreur ? true : undefined}
        aria-describedby={decrit(idChamp, aide, erreur, reste["aria-describedby"])}
      />
    </Cadre>
  );
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size">, ChampCommun {
  ref?: Ref<HTMLSelectElement>;
  options: ReadonlyArray<{ valeur: string; libelle: string }>;
  /** Première option vide (ex. « Choisir… »). */
  placeholder?: string;
}

/** Liste déroulante native, mêmes mesures qu'un champ. */
export function Select({ label, aide, erreur, taille = "normal", labelMasque, classeConteneur, id, className, options, placeholder, ...reste }: SelectProps) {
  const auto = useId();
  const idChamp = id ?? auto;
  return (
    <Cadre {...{ id: idChamp, label, aide, erreur, taille, labelMasque, classeConteneur, required: reste.required }}>
      <select
        {...reste}
        id={idChamp}
        className={cn(classesChamp(taille, !!erreur), "pr-8", className)}
        aria-invalid={erreur ? true : undefined}
        aria-describedby={decrit(idChamp, aide, erreur, reste["aria-describedby"])}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.valeur} value={o.valeur}>
            {o.libelle}
          </option>
        ))}
      </select>
    </Cadre>
  );
}
