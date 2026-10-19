import type { Metadata } from "next";
import { CadreAuth, RetourConnexion } from "@/components/auth/CadreAuth";
import { EcranReinitialisation } from "@/components/auth/EcransMotDePasse";

export const metadata: Metadata = { title: "Nouveau mot de passe" };

export default async function PageReinitialisation({ params }: { params: Promise<{ jeton: string }> }) {
  const { jeton } = await params;
  return (
    <CadreAuth large>
      <EcranReinitialisation jeton={decodeURIComponent(jeton)} />
      <RetourConnexion />
    </CadreAuth>
  );
}
