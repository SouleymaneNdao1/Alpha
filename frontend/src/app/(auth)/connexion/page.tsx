import type { Metadata } from "next";
import { Suspense } from "react";
import { CadreAuth } from "@/components/auth/CadreAuth";
import { EcranConnexion } from "@/components/auth/EcranConnexion";

export const metadata: Metadata = { title: "Connexion" };

export default function PageConnexion() {
  return (
    <CadreAuth>
      <Suspense>
        <EcranConnexion />
      </Suspense>
    </CadreAuth>
  );
}
