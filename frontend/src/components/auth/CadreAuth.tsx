import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Logo ALPHA du prototype (carré ambre arrondi, monogramme blanc). */
export function LogoAlpha({ taille = 44 }: { taille?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={taille} height={taille} aria-hidden="true" className="block flex-none rounded-carte">
      <rect width="64" height="64" rx="14" fill="#A16207" />
      <g transform="translate(-3 0)">
        <path
          d="M40 32 C37 23 31 20 26 20 C19 20 14 26 14 33 C14 40 19 46 26 46 C33 46 37 41 40 32 C42 26 44 21 47 19 M40 32 L44 41 C45.5 44.5 48.5 44.5 50 41 L56 27"
          fill="none"
          stroke="#FFFFFF"
          strokeWidth="5.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}

const PROMESSES = [
  ["Double authentification", "Application Authenticator"],
  ["Journal infalsifiable", "Chaque action tracée"],
  ["Données cloisonnées", "Par établissement"],
] as const;

/**
 * Mise en page des écrans d'authentification (prototype, écrans 01 et 01b) :
 * panneau sombre à gauche (logo, slogan, accroche, trois promesses), carte du
 * formulaire à droite. Sous 960 px, une seule colonne avec le panneau réduit
 * (logo et slogan).
 */
export function CadreAuth({ children, large = false }: { children: ReactNode; large?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col bg-fond lg:flex-row">
      <section
        aria-label="ALPHA"
        className="flex flex-col justify-between gap-6 bg-encre px-4 py-6 text-[#E2E8F0] sm:px-8 lg:min-h-dvh lg:flex-1 lg:basis-[480px] lg:gap-12 lg:px-16 lg:py-14"
      >
        <div className="flex items-center gap-3">
          <LogoAlpha />
          <div className="text-[22px] font-bold tracking-[0.08em] text-white">ALPHA</div>
        </div>
        <div className="flex max-w-[520px] flex-col gap-5">
          <p className="text-[22px] font-semibold leading-[1.2] text-white lg:text-[40px] lg:leading-[1.15]">
            Chaque décision, formalisée, tracée et vérifiable.
          </p>
          <p className="hidden text-[17px] leading-[1.6] text-menu-texte lg:block">
            Plateforme de workflow décisionnel pour les établissements financiers de l&rsquo;UEMOA : dossiers, circuits de validation,
            analyse et fiches de décision authentifiées.
          </p>
        </div>
        <ul className="m-0 hidden max-w-[560px] list-none grid-cols-3 gap-4 p-0 lg:grid">
          {PROMESSES.map(([titre, sous]) => (
            <li key={titre} className="flex flex-col gap-1.5 border-t border-[#334155] pt-3.5">
              <span className="text-[14px] font-semibold text-white">{titre}</span>
              <span className="text-[13px] text-texte-discret">{sous}</span>
            </li>
          ))}
        </ul>
      </section>
      <main className="flex flex-1 items-start justify-center px-4 py-6 sm:items-center sm:px-6 sm:py-12 lg:basis-[480px]">
        <div
          className={cn(
            "flex w-full flex-col rounded-carte border border-bordure bg-surface p-5 sm:p-10",
            large ? "max-w-[460px] gap-[22px] sm:p-9" : "max-w-[420px] gap-6",
          )}
        >
          {children}
        </div>
      </main>
    </div>
  );
}

/** Bandeau d'erreur annoncé immédiatement (`role="alert"`). */
export function AlerteAuth({ ton = "erreur", children, id }: { ton?: "erreur" | "info" | "succes"; children: ReactNode; id?: string }) {
  if (!children) return null;
  const styles = {
    erreur: "border-[#FECACA] bg-badge-rouge-fond text-badge-rouge-texte",
    info: "border-[#BFDBFE] bg-badge-bleu-fond text-badge-bleu-texte",
    succes: "border-[#BBF7D0] bg-badge-vert-fond text-badge-vert-texte",
  }[ton];
  return (
    <div id={id} role={ton === "erreur" ? "alert" : "status"} className={cn("rounded-champ border px-3.5 py-2.5 text-[14px] font-medium", styles)}>
      {children}
    </div>
  );
}

/** Pied de carte « ← Retour à la connexion » (écran 01b). */
export function RetourConnexion() {
  return (
    <div className="border-t border-ligne pt-3.5 text-[13px] text-texte-attenue">
      <Link href="/connexion">← Retour à la connexion</Link>
    </div>
  );
}
