import type { ReactNode } from "react";
import { CoquilleApp } from "@/components/shell/CoquilleApp";

export default function LayoutApp({ children }: { children: ReactNode }) {
  return <CoquilleApp>{children}</CoquilleApp>;
}
