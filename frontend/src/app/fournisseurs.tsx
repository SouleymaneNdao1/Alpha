"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { FournisseurToasts } from "@/components/ui/Toast";
import { creerQueryClient } from "@/lib/query-client";
import "@/lib/zod";

/** Fournisseurs client de toute l'application : TanStack Query et toasts. */
export function Fournisseurs({ children }: { children: ReactNode }) {
  const [client] = useState(creerQueryClient);
  return (
    <QueryClientProvider client={client}>
      <FournisseurToasts>{children}</FournisseurToasts>
    </QueryClientProvider>
  );
}
