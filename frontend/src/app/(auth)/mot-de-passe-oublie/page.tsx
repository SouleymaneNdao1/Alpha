import type { Metadata } from "next";
import { CadreAuth, RetourConnexion } from "@/components/auth/CadreAuth";
import { EcranMotDePasseOublie } from "@/components/auth/EcransMotDePasse";

export const metadata: Metadata = { title: "Mot de passe oublié" };

export default function PageMotDePasseOublie() {
  return (
    <CadreAuth>
      <EcranMotDePasseOublie />
      <RetourConnexion />
    </CadreAuth>
  );
}
