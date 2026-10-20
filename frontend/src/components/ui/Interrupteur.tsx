"use client";

import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface InterrupteurProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange" | "checked"> {
  label: ReactNode;
  description?: ReactNode;
  actif: boolean;
  onChange: (actif: boolean) => void;
}

/** Interrupteur (case à cocher native `role="switch"`) : activable au clavier, état annoncé. */
export function Interrupteur({ label, description, actif, onChange, disabled, className, id, ...reste }: InterrupteurProps) {
  const auto = useId();
  const idChamp = id ?? auto;
  return (
    <div className={cn("flex items-start justify-between gap-4 py-3", className)}>
      <div className="flex min-w-0 flex-col gap-0.5">
        <label htmlFor={idChamp} className="text-[14px] font-semibold text-encre">
          {label}
        </label>
        {description && (
          <p id={`${idChamp}-desc`} className="m-0 text-[13px] text-texte-attenue">
            {description}
          </p>
        )}
      </div>
      <span className="relative inline-flex h-6 w-11 flex-none">
        <input
          {...reste}
          id={idChamp}
          type="checkbox"
          role="switch"
          checked={actif}
          disabled={disabled}
          aria-describedby={description ? `${idChamp}-desc` : undefined}
          onChange={(e) => onChange(e.currentTarget.checked)}
          className="peer absolute inset-0 z-10 m-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        />
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-pilule bg-bordure-champ transition-colors peer-checked:bg-succes peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-alerte-texte peer-disabled:opacity-50"
        />
        <span
          aria-hidden="true"
          className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-segment transition-transform peer-checked:translate-x-5"
        />
      </span>
    </div>
  );
}
