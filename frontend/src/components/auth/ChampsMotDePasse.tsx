"use client";

import type { UseFormRegisterReturn } from "react-hook-form";
import { Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import { z } from "@/lib/zod";

/** Politique du § 4.9 vérifiable côté client (le serveur reste seul juge : historique, mots courants, similarité). */
export const REGLES_MOT_DE_PASSE = [
  { id: "longueur", libelle: "12 caractères minimum", test: (v: string) => v.length >= 12 },
  { id: "categories", libelle: "3 types parmi : minuscule, majuscule, chiffre, symbole", test: (v: string) => categories(v) >= 3 },
] as const;

function categories(v: string): number {
  return [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length;
}

export const schemaNouveauMotDePasse = z
  .object({
    mot_de_passe: z
      .string()
      .min(1, "Saisissez un mot de passe.")
      .refine((v) => v.length >= 12, "Le mot de passe doit contenir au moins 12 caractères.")
      .refine((v) => categories(v) >= 3, "Utilisez au moins 3 types de caractères : minuscule, majuscule, chiffre, symbole."),
    confirmation: z.string().min(1, "Confirmez le mot de passe."),
  })
  .refine((v) => v.mot_de_passe === v.confirmation, { path: ["confirmation"], message: "Les deux mots de passe ne sont pas identiques." });

export type ValeursNouveauMotDePasse = z.infer<typeof schemaNouveauMotDePasse>;

/**
 * « Nouveau mot de passe » + « Confirmer le mot de passe » + aide du prototype
 * et avancement de chaque règle (annoncé poliment aux lecteurs d'écran).
 */
export function ChampsNouveauMotDePasse({
  valeur,
  enregistrerMdp,
  enregistrerConfirmation,
  erreurMdp,
  erreurConfirmation,
  libelle = "Nouveau mot de passe",
}: {
  valeur: string;
  enregistrerMdp: UseFormRegisterReturn;
  enregistrerConfirmation: UseFormRegisterReturn;
  erreurMdp?: string;
  erreurConfirmation?: string;
  libelle?: string;
}) {
  return (
    <>
      <Input
        label={libelle}
        type="password"
        taille="auth"
        autoComplete="new-password"
        erreur={erreurMdp}
        aria-describedby="regles-mdp"
        {...enregistrerMdp}
      />
      <Input
        label="Confirmer le mot de passe"
        type="password"
        taille="auth"
        autoComplete="new-password"
        erreur={erreurConfirmation}
        {...enregistrerConfirmation}
      />
      <div id="regles-mdp" className="flex flex-col gap-1.5">
        <p className="m-0 text-[13px] text-texte-attenue">12 caractères minimum. Évitez votre nom et votre date de naissance.</p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-live="polite">
          {REGLES_MOT_DE_PASSE.map((r) => {
            const ok = r.test(valeur);
            return (
              <li key={r.id} className={cn("flex items-center gap-2 text-[13px]", ok ? "text-succes" : "text-texte-attenue")}>
                <span aria-hidden="true" className="inline-block w-3 text-center font-semibold">
                  {ok ? "✓" : "·"}
                </span>
                {r.libelle}
                <span className="sr-only">{ok ? " : respecté" : " : pas encore respecté"}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
