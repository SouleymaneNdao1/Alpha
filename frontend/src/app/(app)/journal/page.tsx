import type { Metadata } from "next";
import { EcranJournal } from "@/components/audit/EcranJournal";

export const metadata: Metadata = { title: "Journal d'audit" };

export default function PageJournal() {
  return <EcranJournal />;
}
