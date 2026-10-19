"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Tabs } from "@/components/ui";
import { EnTetePage } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { OngletAbsences } from "./OngletAbsences";
import { OngletNotifications } from "./OngletNotifications";
import { OngletProfil } from "./OngletProfil";
import { OngletSecurite } from "./OngletSecurite";

const ONGLETS = ["profil", "securite", "absences", "notifications"] as const;
type IdOnglet = (typeof ONGLETS)[number];

/** `/mon-compte?onglet=profil|securite|absences|notifications` (écran 01d). */
export function EcranMonCompte() {
  const moi = useMoi();
  const params = useSearchParams();
  const router = useRouter();
  const chemin = usePathname();
  const demande = params.get("onglet");
  const actif: IdOnglet = (ONGLETS as readonly string[]).includes(demande ?? "") ? (demande as IdOnglet) : "profil";

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre="Mon compte"
        sousTitre={`${moi.etablissement ? `${moi.etablissement.raison_sociale} · ` : ""}vos informations, votre sécurité, vos absences et vos notifications.`}
      />
      <Tabs
        label="Mon compte"
        actif={actif}
        onChange={(id) => router.replace(`${chemin}?onglet=${id}`, { scroll: false })}
        onglets={[
          { id: "profil", libelle: "Profil", contenu: <OngletProfil /> },
          { id: "securite", libelle: "Sécurité", contenu: <OngletSecurite /> },
          { id: "absences", libelle: "Absences et délégation", contenu: <OngletAbsences /> },
          { id: "notifications", libelle: "Notifications", contenu: <OngletNotifications /> },
        ]}
      />
    </div>
  );
}
