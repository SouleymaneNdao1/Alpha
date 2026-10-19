"use client";

import Link from "next/link";
import { AccesRefuse } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Card } from "@/components/ui";
import { possede } from "@/lib/permissions";

/**
 * `/administration/delegations` : suivi des délégations et absences de l'établissement.
 * Les routes `GET /admin/delegations` et `GET /admin/absences` (architecture § 5.5) ne sont
 * pas encore livrées par le backend : l'écran l'explique au lieu d'afficher une liste vide
 * trompeuse. Les demandes d'absence arrivent déjà dans « À traiter » du valideur.
 */
export function EcranDelegations() {
  const moi = useMoi();
  if (!possede(moi, "admin.utilisateurs") && !possede(moi, "admin.absences")) return <AccesRefuse />;
  return (
    <Card titre="Délégations et absences" description="Suivi des délégations de pouvoirs de l'établissement.">
      <div className="flex max-w-[720px] flex-col gap-3 text-[14px] text-texte-2">
        <p className="m-0" role="status">
          Le suivi centralisé des absences et des délégations n&rsquo;est pas encore disponible : l&rsquo;API d&rsquo;administration correspondante sera livrée dans un
          prochain lot.
        </p>
        <p className="m-0">
          En attendant, chaque demande d&rsquo;absence est envoyée à son valideur, qui la retrouve dans <Link href="/a-traiter">À traiter</Link> et peut la valider ou la refuser.
          Chacun consulte ses propres absences et les délégations reçues dans <Link href="/mon-compte?onglet=absences">Mon compte</Link>.
        </p>
      </div>
    </Card>
  );
}
