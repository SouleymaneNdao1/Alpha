"use client";

import type { ReactNode } from "react";
import { Button, Card } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";

/** En-tête de page : titre h1, sous-titre, actions à droite. */
export function EnTetePage({ titre, sousTitre, actions }: { titre: string; sousTitre?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="m-0 text-titre-page">{titre}</h1>
        {sousTitre && <p className="m-0 max-w-[720px] text-[15px] text-texte-attenue">{sousTitre}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Chargement({ texte = "Chargement…" }: { texte?: string }) {
  return (
    <p className="m-0 text-[15px] text-texte-attenue" role="status">
      {texte}
    </p>
  );
}

export function AccesRefuse({ message = "Vous n'avez pas accès à cet écran." }: { message?: string }) {
  return (
    <Card titre="Accès refusé">
      <p className="m-0 text-[15px] text-texte-2" role="alert">
        {message}
      </p>
    </Card>
  );
}

/** Erreur de chargement : un 403 devient « Accès refusé », le reste propose de réessayer. */
export function ErreurChargement({ erreur, titre = "Données indisponibles", onReessayer }: { erreur: unknown; titre?: string; onReessayer?: () => void }) {
  if (estApiError(erreur) && erreur.estAccesRefuse) return <AccesRefuse />;
  return (
    <Card titre={titre}>
      <p className="m-0 text-[15px] text-texte-2" role="alert">
        {estApiError(erreur) ? erreur.message : "Impossible de charger les données."}
      </p>
      {onReessayer && (
        <div className="mt-3">
          <Button variante="secondaire" onClick={onReessayer}>
            Réessayer
          </Button>
        </div>
      )}
    </Card>
  );
}

/** Message d'erreur d'un formulaire ou d'une action (bandeau rouge). */
export function AlerteErreur({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="m-0 rounded-champ border border-badge-rouge-fond bg-badge-rouge-fond px-3 py-2.5 text-[14px] text-badge-rouge-texte">
      {children}
    </p>
  );
}

export function AlerteInfo({ children, ton = "ambre" }: { children?: ReactNode; ton?: "ambre" | "bleu" }) {
  if (!children) return null;
  return (
    <p
      role="status"
      className={
        ton === "ambre"
          ? "m-0 rounded-champ border border-badge-ambre-fond bg-badge-ambre-fond px-3 py-2.5 text-[14px] text-badge-ambre-texte"
          : "m-0 rounded-champ border border-badge-bleu-fond bg-badge-bleu-fond px-3 py-2.5 text-[14px] text-badge-bleu-texte"
      }
    >
      {children}
    </p>
  );
}
