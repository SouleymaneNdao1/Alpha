import type { Metadata } from "next";
import { EcranUnites } from "@/components/admin/EcranUnites";

export const metadata: Metadata = { title: "Unités et périmètres" };

export default function PageOrganisation() {
  return <EcranUnites />;
}
