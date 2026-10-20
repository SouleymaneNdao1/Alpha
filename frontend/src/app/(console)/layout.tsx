import type { ReactNode } from "react";
import { BandeauConsole } from "@/components/console/BandeauConsole";
import { CoquilleApp } from "@/components/shell/CoquilleApp";

/** Groupe `(console)` : réservé au super-administrateur FYXOP (les autres retournent à « À traiter »). */
export default function LayoutConsole({ children }: { children: ReactNode }) {
  return (
    <CoquilleApp reserveSuperAdmin>
      <BandeauConsole />
      {children}
    </CoquilleApp>
  );
}
