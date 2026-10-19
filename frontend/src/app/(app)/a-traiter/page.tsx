import type { Metadata } from "next";
import { EcranATraiter } from "@/components/taches/EcranATraiter";

export const metadata: Metadata = { title: "À traiter" };

export default function PageATraiter() {
  return <EcranATraiter />;
}
