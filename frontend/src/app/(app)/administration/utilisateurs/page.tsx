import type { Metadata } from "next";
import { PageProvisoire } from "@/components/shell/PageProvisoire";

export const metadata: Metadata = { title: "Utilisateurs et rôles" };

export default function PageUtilisateurs() {
  return (
    <PageProvisoire
      titre="Utilisateurs et rôles"
      tache="F7"
      description="La gestion des comptes, des rôles et des habilitations sera disponible ici."
    />
  );
}
