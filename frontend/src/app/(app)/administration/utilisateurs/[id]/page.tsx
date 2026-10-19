import type { Metadata } from "next";
import { FicheUtilisateur } from "@/components/admin/FicheUtilisateur";

export const metadata: Metadata = { title: "Fiche utilisateur" };

export default async function PageFicheUtilisateur({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <FicheUtilisateur id={id} />;
}
