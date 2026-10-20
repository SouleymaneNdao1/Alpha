import type { Metadata } from "next";
import { FicheEtablissement } from "@/components/console/FicheEtablissement";

export const metadata: Metadata = { title: "Fiche établissement" };

export default async function PageFicheEtablissement({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <FicheEtablissement id={id} />;
}
