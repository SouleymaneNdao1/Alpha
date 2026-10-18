import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DemoComposants } from "./demo-composants";

export const metadata: Metadata = { title: "Composants" };

// Rendu à la demande : ALPHA_ENVIRONNEMENT est lue à l'exécution (la même image
// sert la recette et la production), pas figée au build.
export const dynamic = "force-dynamic";

/** Page de démonstration des composants UI (critère de fin de F1). Masquée en production (D3). */
export default function PageDemo() {
  if (process.env.ALPHA_ENVIRONNEMENT === "production") notFound();
  return <DemoComposants />;
}
