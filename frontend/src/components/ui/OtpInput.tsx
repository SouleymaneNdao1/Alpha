"use client";

import { useId, useRef, type ClipboardEvent, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface OtpInputProps {
  /** Valeur contrôlée : chaîne de 0 à `longueur` chiffres. */
  valeur: string;
  onChange: (valeur: string) => void;
  /** Appelé quand les `longueur` chiffres sont saisis (saisie, collage ou remplissage automatique). */
  onComplete?: (valeur: string) => void;
  longueur?: number;
  label?: ReactNode;
  aide?: ReactNode;
  erreur?: string;
  desactive?: boolean;
  autoFocus?: boolean;
  /** Nom du champ caché portant la valeur complète, pour un envoi de formulaire classique. */
  name?: string;
}

/**
 * Saisie d'un code Authenticator (prototype, écran 01 : cases `.otp` de
 * 52 × 60 px, IBM Plex Mono 600 24 px). Saisie chiffre par chiffre avec
 * passage automatique à la case suivante, collage du code entier, remplissage
 * par le système (`autocomplete="one-time-code"`), flèches, Début/Fin et
 * retour arrière.
 */
export function OtpInput({
  valeur,
  onChange,
  onComplete,
  longueur = 6,
  label = `Code à ${longueur} chiffres`,
  aide,
  erreur,
  desactive,
  autoFocus,
  name,
}: OtpInputProps) {
  const id = useId();
  const cases = useRef<Array<HTMLInputElement | null>>([]);
  const chiffres = Array.from({ length: longueur }, (_, i) => valeur[i] ?? "");
  // Longueur la plus récente, mise à jour dès la saisie : `onFocus` s'exécute pendant
  // `focaliser`, avant le rendu suivant, et lirait sinon une valeur périmée (la case
  // suivante renverrait le focus à la première case et un chiffre sur deux serait perdu).
  const longueurCourante = useRef(valeur.length);
  longueurCourante.current = valeur.length;
  const changer = (v: string) => {
    longueurCourante.current = v.length;
    onChange(v);
  };

  const focaliser = (i: number) => {
    const c = cases.current[Math.max(0, Math.min(longueur - 1, i))];
    c?.focus();
    c?.select();
  };

  // La valeur est toujours un préfixe contigu : pas de case vide au milieu.
  const retirer = (i: number) => chiffres.filter((_, k) => k !== i).join("");

  const ecrire = (depuis: number, saisie: string) => {
    const nouveaux = saisie.replace(/\D/g, "");
    if (!nouveaux) return;
    // Un code complet (collage, remplissage automatique) remplace tout.
    const debut = nouveaux.length >= longueur ? 0 : Math.min(depuis, valeur.length);
    const suite = [...chiffres];
    for (let k = 0; k < nouveaux.length && debut + k < longueur; k++) suite[debut + k] = nouveaux[k]!;
    const resultat = suite.join("").slice(0, longueur);
    changer(resultat);
    focaliser(Math.min(debut + nouveaux.length, longueur - 1));
    if (resultat.length === longueur && !suite.includes("")) onComplete?.(resultat);
  };

  const touche = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case "Backspace":
        e.preventDefault();
        if (chiffres[i]) {
          changer(retirer(i));
        } else if (i > 0) {
          changer(retirer(i - 1));
          focaliser(i - 1);
        }
        break;
      case "ArrowLeft":
        e.preventDefault();
        focaliser(i - 1);
        break;
      case "ArrowRight":
        e.preventDefault();
        focaliser(i + 1);
        break;
      case "Home":
        e.preventDefault();
        focaliser(0);
        break;
      case "End":
        e.preventDefault();
        focaliser(longueur - 1);
        break;
    }
  };

  const coller = (i: number, e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    ecrire(i, e.clipboardData.getData("text"));
  };

  const descr = erreur ? `${id}-erreur` : aide ? `${id}-aide` : undefined;

  return (
    <div className="flex flex-col gap-2">
      <div id={`${id}-label`} className="text-[14px] font-semibold text-texte-2">
        {label}
      </div>
      <div role="group" aria-labelledby={`${id}-label`} aria-describedby={descr} className="flex gap-2">
        {chiffres.map((c, i) => (
          <input
            key={i}
            ref={(el) => {
              cases.current[i] = el;
            }}
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete={i === 0 ? "one-time-code" : "off"}
            aria-label={`Chiffre ${i + 1} sur ${longueur}`}
            aria-invalid={erreur ? true : undefined}
            value={c}
            disabled={desactive}
            autoFocus={autoFocus && i === 0}
            onFocus={(e) => {
              // Pas de case vide au milieu : on renvoie vers la première case libre.
              if (i > longueurCourante.current) focaliser(longueurCourante.current);
              else e.currentTarget.select();
            }}
            onChange={(e) => {
              const v = e.currentTarget.value;
              if (v === "") changer(retirer(i));
              // Une case déjà remplie reçoit un 2e caractère : on garde le nouveau.
              else ecrire(i, c && v.length === 2 ? (v.startsWith(c) ? v.slice(1) : v.slice(0, 1)) : v);
            }}
            onKeyDown={(e) => touche(i, e)}
            onPaste={(e) => coller(i, e)}
            className={cn(
              "h-[60px] w-[52px] min-w-0 flex-1 basis-0 rounded-champ border bg-surface text-center font-mono text-[24px] font-semibold text-encre",
              "max-w-[52px] focus:outline focus:outline-2 focus:outline-marque",
              "disabled:cursor-not-allowed disabled:bg-survol",
              erreur ? "border-danger-texte" : "border-bordure-champ",
            )}
          />
        ))}
      </div>
      {name && <input type="hidden" name={name} value={valeur} />}
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
