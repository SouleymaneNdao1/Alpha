import type { Metadata } from "next";
import { PageProvisoire } from "@/components/shell/PageProvisoire";

export const metadata: Metadata = { title: "Mon compte" };

export default function PageMonCompte() {
  return (
    <PageProvisoire
      titre="Mon compte"
      tache="F6"
      description="Votre profil, votre sécurité, vos absences et vos notifications seront disponibles ici."
    />
  );
}
