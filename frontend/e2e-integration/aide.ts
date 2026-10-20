import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test as base, type BrowserContext, type Page } from "@playwright/test";
import { Secret, TOTP } from "otpauth";
import { DOSSIER_COURRIELS, FICHIER_ACCES, FICHIER_ETAT_TOTP } from "./dossiers.cjs";

/* ------------------------------------------------------------------ comptes */

export interface Acces {
  motDePasse: string;
  secret: string;
  codesSecours: string[];
}

/** Identifiants des comptes de démonstration écrits par `preparer.mjs` (mot de passe, secret TOTP). */
export function acces(email: string): Acces {
  const tous = JSON.parse(readFileSync(FICHIER_ACCES, "utf-8")) as Record<string, Acces>;
  const compte = tous[email];
  if (!compte) throw new Error(`Compte de démonstration inconnu : ${email}`);
  return compte;
}

/** Comptes de démonstration utilisés par la suite (établissement démo, banque). */
export const COMPTES = {
  superAdmin: "superadmin@fyxop-demo.sn",
  /** Administrateur ALPHA de la banque. */
  admin: "s.diouf@etablissement-demo.sn",
  /** Analyste crédit, responsable : Mamadou Sow ; ses tâches personnelles passent au délégataire. */
  absent: "a.diop@etablissement-demo.sn",
  /** Analyste crédit, même rôle que l'absent : délégataire possible (pouvoirs au moins égaux). */
  delegataire: "k.seck@etablissement-demo.sn",
  /** Agent de saisie sans tâche : compte du parcours « téléphone perdu ». */
  telephonePerdu: "i.diallo@etablissement-demo.sn",
} as const;

/* ---------------------------------------------------------------- TOTP */

const PERIODE_S = 30;
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function lireEtatTotp(): Record<string, number> {
  return existsSync(FICHIER_ETAT_TOTP) ? (JSON.parse(readFileSync(FICHIER_ETAT_TOTP, "utf-8")) as Record<string, number>) : {};
}

/**
 * Code Authenticator à 6 chiffres que le serveur acceptera.
 *
 * Le serveur refuse un pas de temps déjà consommé (anti-rejeu, § 4.2) et accepte le pas courant ±1.
 * On retient donc, par secret, le dernier pas utilisé : le code vient du pas courant s'il est libre,
 * sinon du suivant, sinon on attend le pas suivant. L'état est dans un fichier : il survit à un
 * redémarrage du processus de test.
 */
export async function codeTotp(secret: string): Promise<string> {
  const cle = createHash("sha256").update(secret).digest("hex").slice(0, 16);
  for (;;) {
    const etat = lireEtatTotp();
    const pas = Math.floor(Date.now() / 1000 / PERIODE_S);
    const candidat = Math.max(pas, (etat[cle] ?? 0) + 1);
    if (candidat <= pas + 1) {
      etat[cle] = candidat;
      writeFileSync(FICHIER_ETAT_TOTP, JSON.stringify(etat));
      const totp = new TOTP({ algorithm: "SHA1", digits: 6, period: PERIODE_S, secret: Secret.fromBase32(secret.replace(/\s+/g, "")) });
      return totp.generate({ timestamp: candidat * PERIODE_S * 1000 });
    }
    await pause(((pas + 1) * PERIODE_S * 1000) - Date.now() + 250);
  }
}

/* -------------------------------------------------------------- e-mails */

export interface Courriel {
  destinataires: string;
  sujet: string;
  texte: string;
  fichier: string;
}

function decoderTransfert(corps: string, encodage: string): string {
  const e = encodage.toLowerCase();
  if (e === "base64") return Buffer.from(corps.replace(/\s+/g, ""), "base64").toString("utf-8");
  if (e === "quoted-printable") {
    const octets = corps
      .replace(/=\r?\n/g, "")
      .replace(/=([0-9A-Fa-f]{2})/g, (_m, h: string) => String.fromCharCode(parseInt(h, 16)));
    return Buffer.from(octets, "latin1").toString("utf-8");
  }
  return corps;
}

function decoderMotsEncodes(valeur: string): string {
  return valeur.replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=/g, (_m, _charset: string, type: string, contenu: string) =>
    type.toLowerCase() === "b"
      ? Buffer.from(contenu, "base64").toString("utf-8")
      : Buffer.from(
          contenu.replace(/_/g, " ").replace(/=([0-9A-Fa-f]{2})/g, (_x, h: string) => String.fromCharCode(parseInt(h, 16))),
          "latin1",
        ).toString("utf-8"),
  );
}

/** Lit les en-têtes (dépliés) et le corps d'un message MIME. */
function separer(message: string): { entetes: Record<string, string>; corps: string } {
  const coupure = message.search(/\r?\n\r?\n/);
  const brut = coupure === -1 ? message : message.slice(0, coupure);
  const corps = coupure === -1 ? "" : message.slice(coupure).replace(/^\r?\n\r?\n/, "");
  const entetes: Record<string, string> = {};
  for (const ligne of brut.replace(/\r?\n[ \t]+/g, " ").split(/\r?\n/)) {
    const i = ligne.indexOf(":");
    if (i > 0) entetes[ligne.slice(0, i).trim().toLowerCase()] = ligne.slice(i + 1).trim();
  }
  return { entetes, corps };
}

/** Texte lisible d'une partie MIME (récursif pour multipart ; les pièces non textuelles sont ignorées). */
function texteDe(message: string): string {
  const { entetes, corps } = separer(message);
  const type = entetes["content-type"] ?? "text/plain";
  const frontiere = type.match(/boundary="?([^";]+)"?/i)?.[1];
  if (/^multipart\//i.test(type) && frontiere) {
    return corps
      .split(`--${frontiere}`)
      .slice(1)
      .filter((p) => !p.startsWith("--"))
      .map((p) => texteDe(p.replace(/^\r?\n/, "")))
      .join("\n");
  }
  if (!/^text\//i.test(type)) return "";
  return decoderTransfert(corps, entetes["content-transfer-encoding"] ?? "7bit");
}

/** Tous les e-mails écrits par le backend (backend « fichier » de Django : messages séparés par une ligne de tirets). */
export function lireCourriels(): Courriel[] {
  if (!existsSync(DOSSIER_COURRIELS)) return [];
  const courriels: Courriel[] = [];
  for (const nom of readdirSync(DOSSIER_COURRIELS).sort()) {
    const contenu = readFileSync(path.join(DOSSIER_COURRIELS, nom), "utf-8");
    for (const message of contenu.split(/\r?\n-{79}\r?\n/)) {
      if (!message.trim()) continue;
      const { entetes } = separer(message.replace(/^\s+/, ""));
      courriels.push({
        destinataires: decoderMotsEncodes(entetes["to"] ?? ""),
        sujet: decoderMotsEncodes(entetes["subject"] ?? ""),
        texte: texteDe(message.replace(/^\s+/, "")),
        fichier: nom,
      });
    }
  }
  return courriels;
}

/**
 * Attend un e-mail pour `destinataire` dont le sujet correspond à `sujet` et renvoie le jeton du lien
 * qui correspond à `motif` (groupe 1), en partant du message le plus récent.
 */
export async function lienDansCourriel(destinataire: string, sujet: RegExp, motif: RegExp, delaiMs = 20_000): Promise<string> {
  const fin = Date.now() + delaiMs;
  let dernier = "";
  while (Date.now() < fin) {
    const trouves = lireCourriels().filter((c) => c.destinataires.toLowerCase().includes(destinataire.toLowerCase()) && sujet.test(c.sujet));
    for (const courriel of trouves.reverse()) {
      const jeton = courriel.texte.match(motif)?.[1];
      if (jeton) return jeton;
      dernier = `${courriel.sujet} :\n${courriel.texte.slice(0, 400)}`;
    }
    await pause(300);
  }
  throw new Error(`Aucun e-mail « ${sujet} » avec un lien pour ${destinataire}. ${dernier}`);
}

/* -------------------------------------------------------- parcours communs */

/** Sélecteur des alertes de la carte (exclut l'annonceur de routes de Next). */
export const alerte = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');

/** Saisit un code à 6 chiffres dans les 6 cases de OtpInput. */
export async function saisirOtp(page: Page, code: string) {
  await page.getByLabel(/^Chiffre 1 sur 6/).first().click();
  await page.keyboard.type(code);
}

/** Mot de passe puis code Authenticator, jusqu'à l'arrivée sur la page d'accueil de l'utilisateur. */
export async function seConnecter(page: Page, email: string, identifiants: { motDePasse: string; secret: string } = acces(email)) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse e-mail professionnelle").fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(identifiants.motDePasse);
  await page.getByRole("button", { name: "Continuer" }).click();
  await expect(page.getByRole("heading", { name: "Double authentification" })).toBeVisible();
  await saisirOtp(page, await codeTotp(identifiants.secret));
}

export async function seDeconnecter(page: Page, nomAffiche: RegExp) {
  await page.locator("aside").getByRole("button", { name: nomAffiche }).click();
  await page.getByRole("menuitem", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/connexion/);
}

/* ----------------------------------------------------------- test (fixture) */

/**
 * `test` de la suite : chaque test annonce au proxy une adresse IP qui lui est propre
 * (en-tête `x-e2e-ip`, voir proxy.mjs), pour que les limites de débit de la connexion
 * (10/min par IP) ne s'additionnent pas d'un test à l'autre.
 */
export const test = base.extend<{ nouveauContexte: (ip: string) => Promise<BrowserContext> }>({
  context: async ({ context }, utiliser, testInfo) => {
    const octets = createHash("sha256").update(testInfo.testId).digest();
    await context.setExtraHTTPHeaders({ "x-e2e-ip": `10.${octets[0]}.${octets[1]}.${((octets[2] ?? 0) % 250) + 1}` });
    await utiliser(context);
  },
  // Contexte de navigation vierge (aucun cookie), pour jouer une seconde personne dans le même test.
  nouveauContexte: async ({ browser }, utiliser, testInfo) => {
    const ouverts: BrowserContext[] = [];
    await utiliser(async (ip) => {
      const contexte = await browser.newContext({ baseURL: testInfo.project.use.baseURL, locale: "fr-FR", extraHTTPHeaders: { "x-e2e-ip": ip } });
      ouverts.push(contexte);
      return contexte;
    });
    for (const contexte of ouverts) await contexte.close();
  },
});

export { expect };
