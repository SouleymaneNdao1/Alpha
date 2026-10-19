import type { Metadata } from "next";
import { EcranUtilisateurs } from "@/components/admin/EcranUtilisateurs";

export const metadata: Metadata = { title: "Utilisateurs et rôles" };

export default function PageUtilisateurs() {
  return <EcranUtilisateurs />;
}
