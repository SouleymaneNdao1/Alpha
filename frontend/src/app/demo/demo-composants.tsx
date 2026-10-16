"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import {
  Badge,
  Button,
  Card,
  Drawer,
  Input,
  Modal,
  OtpInput,
  Select,
  Stepper,
  Table,
  Tabs,
  Td,
  Th,
  useToast,
  type TonBadge,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError, estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { formatDateHeureCourte, formatMontant } from "@/lib/format";
import { z } from "@/lib/zod";

/* ------------------------------------------------------------------ données */

const JETONS: Array<{ nom: string; valeur: string; usage: string; clair?: boolean }> = [
  { nom: "--encre", valeur: "#0F172A", usage: "Texte, bouton primaire, barre latérale" },
  { nom: "--marque", valeur: "#1E3A8A", usage: "Survol du primaire, menu actif, focus des champs" },
  { nom: "--fond", valeur: "#F1F4F8", usage: "Fond de page", clair: true },
  { nom: "--surface", valeur: "#FFFFFF", usage: "Cartes, champs", clair: true },
  { nom: "--bordure", valeur: "#E2E8F0", usage: "Cartes, en-têtes de tableau", clair: true },
  { nom: "--bordure-champ", valeur: "#808B9C", usage: "Champs, bouton secondaire" },
  { nom: "--texte-2", valeur: "#334155", usage: "Libellés, compteurs" },
  { nom: "--texte-attenue", valeur: "#475569", usage: "Onglets inactifs, en-têtes de colonnes" },
  { nom: "--succes", valeur: "#15803D", usage: "Bouton de validation" },
  { nom: "--danger-texte", valeur: "#B91C1C", usage: "« En retard »" },
  { nom: "--alerte-texte", valeur: "#A16207", usage: "« Aujourd'hui », contour de focus" },
  { nom: "--accent", valeur: "#FBBF24", usage: "Logo ALPHA", clair: true },
];

type Dossier = {
  reference: string;
  client: string;
  produit: string;
  montant: string;
  etape: string;
  echeance: { texte: string; ton: "retard" | "aujourdhui" | "normal" };
  statut: { libelle: string; ton: TonBadge };
  maj: string;
};

const DOSSIERS: Dossier[] = [
  {
    reference: "CR-2026-0412",
    client: "Sow Distribution SARL",
    produit: "Crédit de trésorerie",
    montant: "14600000.00",
    etape: "Comité de crédit",
    echeance: { texte: "En retard d'1 jour", ton: "retard" },
    statut: { libelle: "À décider", ton: "ambre" },
    maj: "2026-10-10T08:02:00Z",
  },
  {
    reference: "CR-2026-0415",
    client: "Awa Ndiaye",
    produit: "Crédit immobilier",
    montant: "38500000.00",
    etape: "Analyse crédit",
    echeance: { texte: "Aujourd'hui, 17:00", ton: "aujourdhui" },
    statut: { libelle: "En cours", ton: "bleu" },
    maj: "2026-10-15T16:41:00Z",
  },
  {
    reference: "CR-2026-0418",
    client: "Teranga Agro SA",
    produit: "Crédit d'équipement",
    montant: "126000000.00",
    etape: "Direction des risques",
    echeance: { texte: "Ven. 17/10", ton: "normal" },
    statut: { libelle: "En cours", ton: "bleu" },
    maj: "2026-10-14T11:15:00Z",
  },
  {
    reference: "CR-2026-0399",
    client: "Moussa Fall",
    produit: "Découvert autorisé",
    montant: "2500000.00",
    etape: "Mise en place",
    echeance: { texte: "—", ton: "normal" },
    statut: { libelle: "Accordé", ton: "vert" },
    maj: "2026-10-09T09:30:00Z",
  },
  {
    reference: "CR-2026-0387",
    client: "Keur Massar Transport",
    produit: "Crédit d'équipement",
    montant: "54000000.00",
    etape: "Clôturé",
    echeance: { texte: "—", ton: "normal" },
    statut: { libelle: "Refusé", ton: "rouge" },
    maj: "2026-10-02T15:05:00Z",
  },
];

const PRODUITS = [
  { valeur: "TRESORERIE", libelle: "Crédit de trésorerie" },
  { valeur: "EQUIPEMENT", libelle: "Crédit d'équipement" },
  { valeur: "IMMOBILIER", libelle: "Crédit immobilier" },
  { valeur: "DECOUVERT", libelle: "Découvert autorisé" },
] as const;

const schemaDossier = z.object({
  client: z.string().trim().min(2, "Indiquez le nom du client ou sa raison sociale."),
  ninea: z
    .string()
    .trim()
    .regex(/^$|^\d{7,9}[A-Z0-9]{0,3}$/, "Le NINEA comporte 7 à 9 chiffres, suivis éventuellement du code de taxe.")
    .optional(),
  produit: z.enum(["TRESORERIE", "EQUIPEMENT", "IMMOBILIER", "DECOUVERT"], { error: "Choisissez un produit de crédit." }),
  montant: z.coerce
    .number<string>({ error: "Saisissez un montant en chiffres." })
    .int("Le montant s'exprime en francs CFA, sans décimales.")
    .min(100_000, "Le montant minimum est de 100 000 FCFA."),
  duree: z.coerce
    .number<string>({ error: "Saisissez une durée en mois." })
    .int()
    .min(1, "La durée minimale est d'1 mois.")
    .max(300, "La durée maximale est de 300 mois."),
});

type EntreeDossier = z.input<typeof schemaDossier>;
type SortieDossier = z.output<typeof schemaDossier>;

/* --------------------------------------------------------------- utilitaires */

function Section({ id, titre, description, children }: { id: string; titre: string; description?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-titre`} className="flex min-w-0 scroll-mt-6 flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-titre`} className="text-[20px] font-semibold leading-tight">
          {titre}
        </h2>
        {description && <p className="text-[14px] text-texte-attenue">{description}</p>}
      </div>
      {children}
    </section>
  );
}

const SOMMAIRE = [
  ["charte", "Charte"],
  ["boutons", "Boutons"],
  ["champs", "Champs"],
  ["otp", "Code à 6 chiffres"],
  ["onglets", "Onglets"],
  ["badges", "Badges"],
  ["tableau", "Tableau"],
  ["stepper", "Étapes"],
  ["fenetres", "Modale et panneau"],
  ["toasts", "Notifications"],
  ["api", "Client d'API"],
] as const;

/* ---------------------------------------------------------------------- page */

export function DemoComposants() {
  return (
    <div className="min-h-dvh">
      <header className="bg-encre text-white">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-4 sm:px-8">
          <span className="font-bold tracking-[.06em] text-accent">ALPHA</span>
          <span className="text-[14px] text-menu-texte">Bibliothèque de composants · socle F1</span>
        </div>
      </header>

      <main className="mx-auto flex max-w-[1200px] flex-col gap-10 px-4 pb-24 pt-8 sm:px-8">
        <div className="flex flex-col gap-2">
          <h1 className="text-titre-page">Composants de l&apos;interface</h1>
          <p className="max-w-[760px] text-[14px] text-texte-attenue">
            Charte relevée dans le prototype (IBM Plex Sans et Mono, jetons de couleur, mesures des boutons, champs, onglets,
            badges et tableaux). Les exemples reprennent le vocabulaire d&apos;ALPHA : dossiers de crédit, code Authenticator,
            délégations.
          </p>
        </div>

        <nav aria-label="Sommaire" className="flex flex-wrap gap-2">
          {SOMMAIRE.map(([id, libelle]) => (
            <a
              key={id}
              href={`#${id}`}
              className="inline-flex min-h-cible items-center rounded-pilule border border-bordure bg-surface px-3.5 text-[13px] font-semibold text-texte-2 no-underline hover:bg-survol hover:text-encre"
            >
              {libelle}
            </a>
          ))}
        </nav>

        <SectionCharte />
        <SectionBoutons />
        <SectionChamps />
        <SectionOtp />
        <SectionOnglets />
        <SectionBadges />
        <SectionTableau />
        <SectionStepper />
        <SectionFenetres />
        <SectionToasts />
        <SectionApi />
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ sections */

function SectionCharte() {
  return (
    <Section id="charte" titre="Charte" description="Jetons de couleur (variables CSS reprises dans tailwind.config.ts) et typographie.">
      <ul className="grid list-none grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3 p-0">
        {JETONS.map((j) => (
          <li key={j.nom} className="flex items-center gap-3 rounded-carte border border-bordure bg-surface p-3">
            <span
              aria-hidden="true"
              className={`h-11 w-11 shrink-0 rounded-champ ${j.clair ? "border border-bordure" : ""}`}
              style={{ background: j.valeur }}
            />
            <span className="flex min-w-0 flex-col">
              <span className="font-mono text-[13px] font-semibold">{j.nom}</span>
              <span className="font-mono text-[12px] text-texte-attenue">{j.valeur}</span>
              <span className="text-[12px] text-texte-attenue">{j.usage}</span>
            </span>
          </li>
        ))}
      </ul>
      <Card titre="Typographie" description="IBM Plex Sans pour le texte, IBM Plex Mono pour les références, montants, horodatages, adresses IP et empreintes.">
        <div className="flex flex-col gap-3">
          <p className="text-titre-page">Bonjour Abdou, voici ce qui vous attend</p>
          <p className="text-titre-carte">Historique des décisions · Utilisateurs et comptes</p>
          <p className="text-[14px]">
            Texte courant 14 px : le dossier a été transmis au comité de crédit avec un avis favorable sous condition.
          </p>
          <p className="text-[13px] font-semibold text-texte-2">Libellé de champ 13 px</p>
          <p className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[14px]">
            <span>CR-2026-0412</span>
            <span>{formatMontant("14600000.00")}</span>
            <span>{formatDateHeureCourte("2026-10-10T20:31:07Z")}</span>
            <span>10.20.4.17</span>
            <span>a41f…9c2e</span>
          </p>
        </div>
      </Card>
    </Section>
  );
}

function SectionBoutons() {
  return (
    <Section id="boutons" titre="Boutons" description="Vrais boutons, focus visible, zone tactile d'au moins 44 px (40 px de hauteur visuelle dans l'application, 44 px sur les écrans d'authentification).">
      <Card>
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap gap-2.5">
            <Button>Décider</Button>
            <Button variante="secondaire">Exporter (Excel)</Button>
            <Button variante="validation">Valider l&apos;absence</Button>
            <Button disabled>Signer</Button>
            <Button chargement>Enregistrement…</Button>
            <Button variante="lien">Utiliser un code de secours</Button>
          </div>
          <div className="flex max-w-[400px] flex-col gap-2.5">
            <p className="text-[13px] font-semibold text-texte-2">Taille « authentification » (44 px, 15 px)</p>
            <Button taille="auth" pleineLargeur>
              Continuer
            </Button>
            <Button taille="auth" variante="secondaire" pleineLargeur>
              ← Retour à la connexion
            </Button>
          </div>
        </div>
      </Card>
    </Section>
  );
}

function SectionChamps() {
  const { toast } = useToast();
  const [erreurGlobale, setErreurGlobale] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<EntreeDossier, unknown, SortieDossier>({
    resolver: zodResolver(schemaDossier),
    defaultValues: { client: "", ninea: "", produit: undefined, montant: "", duree: "" },
  });

  const envoyer = async (d: SortieDossier) => {
    setErreurGlobale(null);
    await new Promise((r) => setTimeout(r, 600));
    toast({
      ton: "succes",
      titre: "Dossier CR-2026-0419 créé",
      message: `${d.client} · ${formatMontant(d.montant)} sur ${d.duree} mois (démonstration, rien n'est envoyé).`,
    });
    reset();
  };

  const simulerErreurApi = () => {
    const erreur = new ApiError({
      status: 400,
      code: "VALIDATION",
      message: "Certaines données sont invalides.",
      details: {
        montant: ["Ce montant dépasse la limite de délégation de l'agence (100 000 000 FCFA)."],
        non_field_errors: ["Le client a déjà un dossier en cours d'instruction (CR-2026-0415)."],
      },
    });
    setErreurGlobale(appliquerErreursApi(erreur, setError, ["client", "ninea", "produit", "montant", "duree"]));
  };

  return (
    <Section id="champs" titre="Champs" description="Libellé relié au champ, aide et erreur annoncées (aria-describedby, aria-invalid). Formulaire react-hook-form + zod, messages en français.">
      <Card titre="Nouveau dossier de crédit" description="Exemple de formulaire : les erreurs s'affichent à l'envoi.">
        <form noValidate onSubmit={handleSubmit(envoyer)} className="flex flex-col gap-4">
          {erreurGlobale && (
            <p role="alert" className="rounded-champ bg-badge-rouge-fond px-3 py-2.5 text-[13px] font-medium text-badge-rouge-texte">
              {erreurGlobale}
            </p>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Client" required autoComplete="organization" placeholder="Nom ou raison sociale" erreur={errors.client?.message} {...register("client")} />
            <Input label="NINEA (facultatif)" inputMode="numeric" aide="Numéro d'identification nationale des entreprises." erreur={errors.ninea?.message} {...register("ninea")} />
            <Select label="Produit" required placeholder="Choisir un produit…" options={PRODUITS} erreur={errors.produit?.message} {...register("produit")} />
            <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4">
              <Input label="Montant demandé (FCFA)" required inputMode="numeric" className="text-right font-mono" erreur={errors.montant?.message} {...register("montant")} />
              <Input label="Durée (mois)" required inputMode="numeric" erreur={errors.duree?.message} {...register("duree")} />
            </div>
            <Input label="Agence" value="Dakar-Plateau" readOnly aide="Déduite de votre périmètre." />
            <Input label="Chargé de clientèle" value="Abdou Kane" disabled />
          </div>
          <div className="flex flex-wrap justify-end gap-2.5">
            <Button variante="secondaire" onClick={simulerErreurApi}>
              Simuler une erreur de l&apos;API
            </Button>
            <Button type="submit" chargement={isSubmitting}>
              Créer le dossier
            </Button>
          </div>
        </form>
      </Card>
    </Section>
  );
}

function SectionOtp() {
  const { toast } = useToast();
  const [code, setCode] = useState("");
  const [erreur, setErreur] = useState<string>();
  const [verif, setVerif] = useState(false);

  const verifier = async (valeur: string) => {
    setVerif(true);
    setErreur(undefined);
    await new Promise((r) => setTimeout(r, 400));
    setVerif(false);
    if (valeur === "000000") {
      setErreur("Code incorrect. Il vous reste 4 tentatives.");
      setCode("");
    } else {
      toast({ ton: "succes", titre: "Code accepté", message: "Double authentification réussie (démonstration)." });
      setCode("");
    }
  };

  return (
    <Section id="otp" titre="Code à 6 chiffres" description="Cases de 52 × 60 px en IBM Plex Mono. Collage du code entier, remplissage automatique (autocomplete=&quot;one-time-code&quot;), flèches et retour arrière. Saisissez 000000 pour voir l'erreur.">
      <Card className="max-w-[460px]">
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="text-titre-auth">Double authentification</h3>
            <p className="mt-1.5 text-[15px] text-texte-attenue">Ouvrez votre application Authenticator.</p>
          </div>
          <OtpInput
            label="Code Authenticator"
            valeur={code}
            onChange={(v) => {
              setCode(v);
              if (erreur) setErreur(undefined);
            }}
            onComplete={verifier}
            erreur={erreur}
            aide="Saisissez le code à 6 chiffres affiché dans Google ou Microsoft Authenticator."
            desactive={verif}
          />
          <Button taille="auth" pleineLargeur chargement={verif} disabled={code.length < 6} onClick={() => verifier(code)}>
            Vérifier
          </Button>
          <Button variante="lien" className="self-start">
            Utiliser un code de secours
          </Button>
        </div>
      </Card>
    </Section>
  );
}

function SectionOnglets() {
  return (
    <Section id="onglets" titre="Onglets" description="Motif WAI-ARIA : flèches gauche/droite, Début et Fin ; seul l'onglet actif est dans l'ordre de tabulation.">
      <Card>
        <div className="flex flex-col gap-8">
          <Tabs
            label="Mon compte"
            onglets={[
              { id: "profil", libelle: "Profil", contenu: <p className="text-[14px]">Nom complet, e-mail professionnel (lecture seule), téléphone mobile, langue.</p> },
              { id: "securite", libelle: "Sécurité", contenu: <p className="text-[14px]">Mot de passe, Authenticator, codes de secours (7 sur 10 restants), appareils et sessions.</p> },
              { id: "absences", libelle: "Absences et délégation", compteur: 1, contenu: <p className="text-[14px]">Absence du 20/10 au 24/10 · délégation à Awa Diop · <Badge ton="ambre">Soumise</Badge></p> },
              { id: "notifications", libelle: "Notifications", contenu: <p className="text-[14px]">Les alertes de sécurité sont toujours envoyées par e-mail.</p> },
            ]}
          />
          <div className="max-w-[460px]">
            <p className="mb-2 text-[13px] font-semibold text-texte-2">Variante segmentée (écran d&apos;activation)</p>
            <Tabs
              label="Situation"
              variante="segmente"
              onglets={[
                { id: "premiere", libelle: "Première connexion", contenu: <p className="text-[14px]">Choisissez votre mot de passe puis enregistrez ALPHA dans votre application Authenticator.</p> },
                { id: "perdu", libelle: "Téléphone perdu", contenu: <p className="text-[14px]">Votre Authenticator sera suspendu et votre administrateur prévenu.</p> },
              ]}
            />
          </div>
        </div>
      </Card>
    </Section>
  );
}

function SectionBadges() {
  const groupes: Array<[string, Array<[string, TonBadge]>]> = [
    ["Comptes", [["Actif", "vert"], ["Invité", "bleu"], ["Suspendu", "ambre"], ["Verrouillé", "rouge"]]],
    ["Authenticator", [["Activée", "vert"], ["Non configurée", "ambre"], ["Suspendue", "rouge"]]],
    ["Absences", [["Soumise", "ambre"], ["Validée", "vert"], ["Refusée", "rouge"], ["Annulée", "gris"]]],
    ["Divers", [["Cette session", "bleu"], ["Vacant", "ambre"], ["par délégation de Mamadou Sow", "gris"]]],
  ];
  return (
    <Section id="badges" titre="Badges" description="Pilules de statut : le sens est porté par le texte, la couleur ne fait que le renforcer.">
      <Card>
        <dl className="grid gap-4 sm:grid-cols-2">
          {groupes.map(([titre, badges]) => (
            <div key={titre} className="flex flex-col gap-2">
              <dt className="text-[13px] font-semibold text-texte-2">{titre}</dt>
              <dd className="m-0 flex flex-wrap gap-2">
                {badges.map(([libelle, ton]) => (
                  <Badge key={libelle} ton={ton}>
                    {libelle}
                  </Badge>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </Card>
    </Section>
  );
}

function SectionTableau() {
  const couleurEcheance = { retard: "text-danger-texte font-semibold", aujourdhui: "text-alerte-texte font-semibold", normal: "text-texte-2" };
  return (
    <Section id="tableau" titre="Tableau" description="Sous 768 px, le tableau défile horizontalement dans sa carte, jamais la page entière. Montants en Mono alignés à droite.">
      <Card titre="Dossiers de crédit" description="Agence Dakar-Plateau · 5 dossiers" marge={false} actions={<Button variante="secondaire">Exporter</Button>}>
        <Table legende="Dossiers de crédit de l'agence Dakar-Plateau">
          <thead>
            <tr>
              <Th>Référence</Th>
              <Th>Client</Th>
              <Th>Produit</Th>
              <Th num>Montant</Th>
              <Th>Étape</Th>
              <Th>Échéance</Th>
              <Th>Statut</Th>
              <Th>Mise à jour</Th>
              <Th>
                <span className="sr-only">Action</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {DOSSIERS.map((d) => (
              <tr key={d.reference}>
                <Td mono className="font-semibold">
                  {d.reference}
                </Td>
                <Td>{d.client}</Td>
                <Td>{d.produit}</Td>
                <Td num>{formatMontant(d.montant)}</Td>
                <Td>{d.etape}</Td>
                <Td className={couleurEcheance[d.echeance.ton]}>{d.echeance.texte}</Td>
                <Td>
                  <Badge ton={d.statut.ton}>{d.statut.libelle}</Badge>
                </Td>
                <Td mono>{formatDateHeureCourte(d.maj)}</Td>
                <Td className="text-right">
                  <Button variante="secondaire" aria-label={`Ouvrir le dossier ${d.reference}`}>
                    Ouvrir
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </Section>
  );
}

function SectionStepper() {
  const etapes = ["Mot de passe", "Téléphone", "Vérification"] as const;
  const [courante, setCourante] = useState(0);
  return (
    <Section id="stepper" titre="Étapes" description="Indicateur de progression de l'activation du compte ; l'étape en cours porte aria-current=&quot;step&quot;.">
      <Card className="max-w-[460px]">
        <div className="flex flex-col gap-5">
          <Stepper etapes={etapes} courante={courante} />
          <p className="text-[14px]" aria-live="polite">
            Étape {courante + 1} sur {etapes.length} : <strong>{etapes[courante]}</strong>
          </p>
          <div className="flex flex-wrap justify-between gap-2.5">
            <Button variante="secondaire" disabled={courante === 0} onClick={() => setCourante((c) => c - 1)}>
              Précédent
            </Button>
            <Button disabled={courante === etapes.length - 1} onClick={() => setCourante((c) => c + 1)}>
              Continuer
            </Button>
          </div>
        </div>
      </Card>
    </Section>
  );
}

function SectionFenetres() {
  const { toast } = useToast();
  const [modale, setModale] = useState(false);
  const [panneau, setPanneau] = useState(false);
  const [envoi, setEnvoi] = useState(false);

  const confirmer = async () => {
    setEnvoi(true);
    await new Promise((r) => setTimeout(r, 700));
    setEnvoi(false);
    setModale(false);
    toast({ ton: "succes", titre: "Décision enregistrée", message: "CR-2026-0412 · favorable sous condition. L'action est tracée dans le journal d'audit." });
  };

  return (
    <Section id="fenetres" titre="Modale et panneau latéral" description="Élément <dialog> natif : focus piégé, Échap pour fermer, retour du focus au bouton d'origine.">
      <Card>
        <div className="flex flex-wrap gap-2.5">
          <Button onClick={() => setModale(true)}>Décider</Button>
          <Button variante="secondaire" onClick={() => setPanneau(true)}>
            + Nouveau rôle
          </Button>
        </div>
      </Card>

      <Modal
        ouvert={modale}
        onFermer={() => setModale(false)}
        fermable={!envoi}
        titre="Confirmer la décision"
        description="Dossier CR-2026-0412 · Sow Distribution SARL"
        pied={
          <>
            <Button variante="secondaire" onClick={() => setModale(false)} disabled={envoi}>
              Annuler
            </Button>
            <Button variante="validation" onClick={confirmer} chargement={envoi}>
              Confirmer la décision
            </Button>
          </>
        }
      >
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-[14px]">
          <dt className="text-texte-attenue">Montant</dt>
          <dd className="m-0 font-mono">{formatMontant("14600000.00")}</dd>
          <dt className="text-texte-attenue">Avis</dt>
          <dd className="m-0">Favorable sous condition</dd>
          <dt className="text-texte-attenue">Condition</dt>
          <dd className="m-0">Caution personnelle du gérant et domiciliation des recettes.</dd>
        </dl>
        <p className="mt-4 text-[13px] text-texte-attenue">Une fois confirmée, la décision ne peut plus être modifiée.</p>
      </Modal>

      <Drawer
        ouvert={panneau}
        onFermer={() => setPanneau(false)}
        titre="Nouveau rôle"
        description="Le rôle s'ajoute au catalogue de l'établissement."
        pied={
          <>
            <Button variante="secondaire" onClick={() => setPanneau(false)}>
              Annuler
            </Button>
            <Button
              onClick={() => {
                setPanneau(false);
                toast({ ton: "succes", titre: "Rôle « Chargé de recouvrement » créé" });
              }}
            >
              Créer le rôle
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input label="Libellé" defaultValue="Chargé de recouvrement" />
          <Input label="Description" defaultValue="Suit les impayés et propose les mesures de recouvrement." />
          <Select
            label="Unité de rattachement"
            defaultValue="RISQUES"
            options={[
              { valeur: "RISQUES", libelle: "Direction des risques" },
              { valeur: "CREDIT", libelle: "Direction du crédit" },
              { valeur: "DAF", libelle: "Direction administrative et financière" },
            ]}
          />
        </div>
      </Drawer>
    </Section>
  );
}

function SectionToasts() {
  const { toast } = useToast();
  return (
    <Section id="toasts" titre="Notifications" description="Annoncées aux lecteurs d'écran ; les erreurs restent affichées jusqu'à leur fermeture.">
      <Card>
        <div className="flex flex-wrap gap-2.5">
          <Button variante="secondaire" onClick={() => toast({ ton: "succes", titre: "Absence validée", message: "Awa Diop recevra vos demandes du 20/10 au 24/10." })}>
            Succès
          </Button>
          <Button variante="secondaire" onClick={() => toast({ ton: "info", titre: "Nouvelle tâche", message: "ED-2026-0077 · 40 postes informatiques vous attend." })}>
            Information
          </Button>
          <Button variante="secondaire" onClick={() => toast({ ton: "alerte", titre: "Votre session va expirer", message: "Dans 60 secondes, faute d'activité." })}>
            Alerte
          </Button>
          <Button variante="secondaire" onClick={() => toast({ ton: "erreur", titre: "Signature impossible", message: "Votre signature est bloquée tant que votre téléphone perdu n'est pas remplacé." })}>
            Erreur
          </Button>
        </div>
      </Card>
    </Section>
  );
}

function SectionApi() {
  const session = useQuery({
    queryKey: ["demo", "auth", "session"],
    queryFn: () => api.get("/auth/session", { redirigerSiSessionExpiree: false }),
    enabled: false,
    retry: false,
  });
  const err = session.error;

  return (
    <Section id="api" titre="Client d'API" description="fetch avec credentials: &quot;include&quot;, X-CSRFToken lu dans le cookie alpha_csrf pour les méthodes non sûres, erreurs {code, message, details} converties en ApiError.">
      <Card titre="Appel de démonstration" description="GET /api/v1/auth/session via TanStack Query (sans redirection automatique).">
        <div className="flex flex-col gap-4">
          <div>
            <Button variante="secondaire" chargement={session.isFetching} onClick={() => session.refetch()}>
              Appeler GET /api/v1/auth/session
            </Button>
          </div>
          <div aria-live="polite" className="min-h-[24px]">
            {session.isSuccess && (
              <p className="text-[14px]">
                <Badge ton="vert">200</Badge> Session ouverte.
              </p>
            )}
            {err && (
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 rounded-champ border border-bordure bg-entete-tableau p-3 text-[13px]">
                <dt className="text-texte-attenue">Statut</dt>
                <dd className="m-0 font-mono">{estApiError(err) ? err.status : "—"}</dd>
                <dt className="text-texte-attenue">Code</dt>
                <dd className="m-0 font-mono font-semibold">{estApiError(err) ? err.code : err.name}</dd>
                <dt className="text-texte-attenue">Message</dt>
                <dd className="m-0">{err.message}</dd>
                {estApiError(err) && err.requestId && (
                  <>
                    <dt className="text-texte-attenue">X-Request-ID</dt>
                    <dd className="m-0 break-all font-mono">{err.requestId}</dd>
                  </>
                )}
              </dl>
            )}
          </div>
        </div>
      </Card>
    </Section>
  );
}
