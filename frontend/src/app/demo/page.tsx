import type { Metadata } from "next";
import { DemoComposants } from "./demo-composants";

export const metadata: Metadata = { title: "Composants" };

/** Page de démonstration des composants UI (critère de fin de F1). */
export default function PageDemo() {
  return <DemoComposants />;
}
