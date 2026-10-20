// Prépare la base et les comptes de la suite d'intégration (lancé avant Playwright par `npm run test:e2e:integration`).
//
//  1. remet la base à zéro (reinitialiser_base.py) puis applique les migrations avec alpha_owner ;
//  2. vide le cache Redis (limites de débit, sessions) ;
//  3. sème le jeu de démonstration (`manage.py semer_demo`, réglages config.settings.e2e) ;
//  4. lit ACCES.txt et écrit acces.json : mot de passe, secret TOTP et codes de secours de chaque compte.
//
// Variables d'environnement attendues : celles du backend (DATABASE_URL = alpha_app, DATABASE_URL_OWNER,
// REDIS_URL, CELERY_BROKER_URL, DJANGO_SECRET_KEY, ALPHA_CLES_CHIFFREMENT, ALPHA_HMAC_POIVRE).
// ALPHA_E2E_PYTHON : interpréteur Python du backend (défaut « python »).
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DOSSIER_COURRIELS, DOSSIER_DEMO, DOSSIER_EXECUTION, FICHIER_ACCES, RACINE_BACKEND, RACINE_FRONTEND } from "./dossiers.cjs";

const python = process.env.ALPHA_E2E_PYTHON ?? "python";
const manquantes = ["DATABASE_URL", "DATABASE_URL_OWNER", "REDIS_URL", "CELERY_BROKER_URL", "DJANGO_SECRET_KEY", "ALPHA_CLES_CHIFFREMENT", "ALPHA_HMAC_POIVRE"].filter(
  (nom) => !process.env[nom],
);
if (manquantes.length > 0) {
  console.error(`Variables d'environnement manquantes : ${manquantes.join(", ")}`);
  process.exit(1);
}

rmSync(DOSSIER_EXECUTION, { recursive: true, force: true });
mkdirSync(DOSSIER_COURRIELS, { recursive: true });

const env = {
  ...process.env,
  DJANGO_SETTINGS_MODULE: "config.settings.e2e",
  ALPHA_E2E_DOSSIER_EMAILS: DOSSIER_COURRIELS,
};
// `muet` : la sortie standard n'est pas relayée (semer_demo y affiche mots de passe et secrets).
const lancer = (etape, args, surcharge = {}, muet = false) => {
  console.log(`[préparation] ${etape}`);
  execFileSync(python, args, { cwd: RACINE_BACKEND, env: { ...env, ...surcharge }, stdio: ["ignore", muet ? "ignore" : "inherit", "inherit"] });
};

lancer("remise à zéro de la base", [path.join(RACINE_FRONTEND, "e2e-integration", "reinitialiser_base.py")]);
lancer("migrations (alpha_owner)", ["manage.py", "migrate", "--noinput", "-v", "0"], { DATABASE_URL: process.env.DATABASE_URL_OWNER });
lancer("cache Redis", ["manage.py", "shell", "-c", "from django.core.cache import cache; cache.clear()"]);
lancer("jeu de démonstration", ["manage.py", "semer_demo", "--sortie", DOSSIER_DEMO, "-v", "0"], {}, true);

// ACCES.txt : un bloc « Compte … E-mail … Mot de passe … Secret TOTP … Codes de secours … » par compte.
const texte = readFileSync(path.join(DOSSIER_DEMO, "ACCES.txt"), "utf-8");
const acces = {};
for (const bloc of texte.split(/^Compte\s+: /m).slice(1)) {
  const champ = (libelle) => bloc.match(new RegExp(`^${libelle}\\s*: (.+)$`, "m"))?.[1]?.trim();
  const email = champ("E-mail");
  const motDePasse = champ("Mot de passe");
  const secret = champ("Secret TOTP");
  const codes = champ("Codes de secours \\(usage unique\\)");
  if (!email || !motDePasse || !secret) throw new Error(`Bloc ACCES.txt illisible :\n${bloc.slice(0, 200)}`);
  acces[email] = { motDePasse, secret, codesSecours: codes ? codes.split(/\s+/) : [] };
}
if (Object.keys(acces).length < 10) throw new Error(`Seulement ${Object.keys(acces).length} compte(s) lus dans ACCES.txt.`);
writeFileSync(FICHIER_ACCES, JSON.stringify(acces, null, 2));
console.log(`[préparation] ${Object.keys(acces).length} comptes prêts (${FICHIER_ACCES}).`);
