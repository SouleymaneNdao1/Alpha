import type { Metadata } from "next";
import { CadreAuth, RetourConnexion } from "@/components/auth/CadreAuth";
import { ParcoursEnrolement } from "@/components/auth/ParcoursEnrolement";

export const metadata: Metadata = { title: "Nouveau téléphone" };

export default async function PageReenrolement({ params }: { params: Promise<{ jeton: string }> }) {
  const { jeton } = await params;
  return (
    <CadreAuth large>
      <ParcoursEnrolement parcours="reenrolement" jeton={decodeURIComponent(jeton)} />
      <RetourConnexion />
    </CadreAuth>
  );
}
