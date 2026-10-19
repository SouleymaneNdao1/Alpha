import type { Metadata } from "next";
import { ATraiterProvisoire } from "./provisoire";

export const metadata: Metadata = { title: "À traiter" };

/** Page provisoire : l'écran « À traiter » (01c) est la tâche F5. */
export default function PageATraiter() {
  return <ATraiterProvisoire />;
}
