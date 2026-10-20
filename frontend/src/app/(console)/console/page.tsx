import type { Metadata } from "next";
import { EcranEtablissements } from "@/components/console/EcranEtablissements";

export const metadata: Metadata = { title: "Console FYXOP" };

export default function PageConsole() {
  return <EcranEtablissements />;
}
