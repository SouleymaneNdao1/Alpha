import type { Metadata } from "next";
import { EcranJournalPlateforme } from "@/components/console/EcranJournalPlateforme";

export const metadata: Metadata = { title: "Journal de la plateforme" };

export default function PageJournalPlateforme() {
  return <EcranJournalPlateforme />;
}
