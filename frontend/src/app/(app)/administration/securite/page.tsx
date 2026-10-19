import type { Metadata } from "next";
import { EcranSecuriteAdmin } from "@/components/admin/EcranSecuriteAdmin";

export const metadata: Metadata = { title: "Sécurité de l'établissement" };

export default function PageSecuriteAdmin() {
  return <EcranSecuriteAdmin />;
}
