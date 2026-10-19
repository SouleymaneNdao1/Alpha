import type { Metadata } from "next";
import { EcranHabilitations } from "@/components/admin/EcranHabilitations";

export const metadata: Metadata = { title: "Rôles et habilitations" };

export default function PageHabilitations() {
  return <EcranHabilitations />;
}
