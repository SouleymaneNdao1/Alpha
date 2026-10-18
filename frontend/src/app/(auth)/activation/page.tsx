import type { Metadata } from "next";
import { Suspense } from "react";
import { CadreAuth, RetourConnexion } from "@/components/auth/CadreAuth";
import { EcranActivation } from "@/components/auth/EcranActivation";

export const metadata: Metadata = { title: "Activation du compte" };

export default function PageActivation() {
  return (
    <CadreAuth large>
      <Suspense>
        <EcranActivation />
      </Suspense>
      <RetourConnexion />
    </CadreAuth>
  );
}
