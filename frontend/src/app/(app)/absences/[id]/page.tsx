import type { Metadata } from "next";
import { EcranValidationAbsence } from "@/components/compte/EcranValidationAbsence";

export const metadata: Metadata = { title: "Demande d'absence" };

export default async function PageAbsence({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EcranValidationAbsence id={id} />;
}
