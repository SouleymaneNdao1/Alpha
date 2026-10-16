import type { Config } from "tailwindcss";

/**
 * Jetons de la charte ALPHA (architecture § 7.3), relevés dans le CSS du
 * prototype. Les valeurs vivent dans src/app/globals.css (variables CSS) ;
 * Tailwind ne fait que les nommer, pour qu'aucune couleur ne soit codée en dur
 * dans les composants. Le prototype n'a pas de mode sombre : pas de variante `dark`.
 */
const v = (nom: string) => `var(--${nom})`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        encre: v("encre"),
        marque: v("marque"),
        fond: v("fond"),
        surface: v("surface"),
        bordure: v("bordure"),
        "bordure-champ": v("bordure-champ"),
        ligne: v("ligne"),
        "entete-tableau": v("entete-tableau"),
        survol: v("survol"),
        "texte-2": v("texte-2"),
        "texte-attenue": v("texte-attenue"),
        "texte-discret": v("texte-discret"),
        "menu-texte": v("menu-texte"),
        "menu-survol": v("menu-survol"),
        succes: { DEFAULT: v("succes"), survol: v("succes-survol") },
        "danger-texte": v("danger-texte"),
        "alerte-texte": v("alerte-texte"),
        accent: v("accent"),
        voile: v("voile"),
        desactive: { DEFAULT: v("desactive"), texte: v("desactive-texte") },
        badge: {
          "vert-fond": v("badge-vert-fond"),
          "vert-texte": v("badge-vert-texte"),
          "ambre-fond": v("badge-ambre-fond"),
          "ambre-texte": v("badge-ambre-texte"),
          "rouge-fond": v("badge-rouge-fond"),
          "rouge-texte": v("badge-rouge-texte"),
          "bleu-fond": v("badge-bleu-fond"),
          "bleu-texte": v("badge-bleu-texte"),
          "gris-fond": v("badge-gris-fond"),
          "gris-texte": v("badge-gris-texte"),
        },
      },
      fontFamily: {
        sans: [v("police-sans"), "system-ui", "sans-serif"],
        mono: [v("police-mono"), "ui-monospace", "monospace"],
      },
      fontSize: {
        // [taille, interligne] relevés dans le prototype
        "titre-page": ["26px", { lineHeight: "1.25", fontWeight: "600" }],
        "titre-auth": ["22px", { lineHeight: "1.3", fontWeight: "600" }],
        "titre-carte": ["17px", { lineHeight: "1.35", fontWeight: "600" }],
        th: ["12px", { lineHeight: "1.4", letterSpacing: ".04em", fontWeight: "600" }],
      },
      borderRadius: {
        champ: v("rayon-champ"),
        carte: v("rayon-carte"),
        segment: v("rayon-segment"),
        pilule: "999px",
      },
      boxShadow: {
        segment: v("ombre-segment"),
        flottante: v("ombre-flottante"),
        "menu-actif": v("ombre-menu-actif"),
      },
      height: { bouton: "40px", "bouton-auth": "44px", champ: "42px", "champ-auth": "44px" },
      minHeight: { bouton: "40px", "bouton-auth": "44px", cible: "44px" },
      minWidth: { cible: "44px" },
      spacing: { "4.5": "18px", "2.75": "11px" },
    },
  },
  plugins: [],
};

export default config;
