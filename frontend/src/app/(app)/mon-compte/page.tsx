import type { Metadata } from "next";
import { Suspense } from "react";
import { EcranMonCompte } from "@/components/compte/EcranMonCompte";

export const metadata: Metadata = { title: "Mon compte" };

export default function PageMonCompte() {
  return (
    <Suspense>
      <EcranMonCompte />
    </Suspense>
  );
}
