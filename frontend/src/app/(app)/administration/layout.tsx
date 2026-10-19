import type { ReactNode } from "react";
import { GabaritAdministration } from "@/components/admin/NavigationAdministration";

export default function LayoutAdministration({ children }: { children: ReactNode }) {
  return <GabaritAdministration>{children}</GabaritAdministration>;
}
