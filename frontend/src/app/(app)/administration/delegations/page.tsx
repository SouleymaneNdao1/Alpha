import type { Metadata } from "next";
import { EcranDelegations } from "@/components/admin/EcranDelegations";

export const metadata: Metadata = { title: "Délégations" };

export default function PageDelegations() {
  return <EcranDelegations />;
}
