import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Fournisseurs } from "./fournisseurs";
import { plexMono, plexSans } from "./polices";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ALPHA", template: "%s · ALPHA" },
  description: "ALPHA — chaque décision, formalisée, tracée et vérifiable.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0F172A",
};

export default function RacineLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <Fournisseurs>{children}</Fournisseurs>
      </body>
    </html>
  );
}
