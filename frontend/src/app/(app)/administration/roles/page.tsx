import type { Metadata } from "next";
import { EcranCatalogueRoles } from "@/components/admin/EcranCatalogueRoles";

export const metadata: Metadata = { title: "Catalogue des rôles" };

export default function PageRoles() {
  return <EcranCatalogueRoles />;
}
