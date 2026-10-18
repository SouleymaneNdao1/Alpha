<!-- Généré depuis docs/architecture-sprint1.md -->
## 7. Écrans frontend du sprint 1


### 7.1 Routes Next.js (App Router)

| Route | Groupe / layout | Écran du prototype | Appels d'API |
|---|---|---|---|
| `/` | — | — | redirection vers `/a-traiter` (ou `/console` pour un super-admin) |
| `/connexion` | `(auth)` | 01 · Connexion + double authentification | `GET /auth/csrf`, `POST /auth/connexion`, `POST /auth/mfa` |
| `/activation?jeton=…&onglet=premiere-connexion\|telephone-perdu` | `(auth)` | 01b · Activation du compte et téléphone perdu | `GET /auth/activation/{j}`, `POST …/mot-de-passe`, `…/authenticator`, `…/authenticator/confirmer`, `…/terminer` ; onglet 2 : `POST /auth/telephone-perdu` |
| `/reenrolement/[jeton]` | `(auth)` | dérivé de 01b | `/auth/reenrolement/{j}/…` |
| `/mot-de-passe-oublie` | `(auth)` | lien « Mot de passe oublié ? » | `POST /auth/mot-de-passe/oubli` |
| `/reinitialisation/[jeton]` | `(auth)` | — | `GET`/`POST /auth/mot-de-passe/reinitialisation/{j}` |
| `/a-traiter` | `(app)` | 01c · À traiter | `GET /taches`, `GET /taches/compteurs` |
| `/mon-compte?onglet=profil\|securite\|absences\|notifications` | `(app)` | 01d · Mon compte | `/moi`, `/moi/securite`, `/moi/sessions`, `/moi/absences`, `/moi/delegataires-possibles`, `/moi/delegations-recues`, `/moi/preferences-notification`, `/moi/authenticator/changement…`, `/moi/codes-secours`, `/moi/telephone-perdu`, `/moi/mot-de-passe` |
| `/absences/[id]` | `(app)` | — (cible des tâches de validation) | `GET /absences/{id}`, `POST …/valider`, `POST …/refuser` |
| `/administration/utilisateurs` | `(app)/administration` | 12 · onglet « Utilisateurs » | `GET /admin/utilisateurs`, `GET /admin/roles`, `GET /admin/utilisateurs/historique`, `POST /admin/utilisateurs` (modale « + Inviter un utilisateur ») |
| `/administration/utilisateurs/[id]` | idem | « Modifier » | `GET/PATCH /admin/utilisateurs/{id}`, affectations, suspendre, réactiver, déverrouiller, renvoyer l'invitation, révoquer les sessions, signalement |
| `/administration/roles` | idem | 12 · onglet « Catalogue des rôles » | `GET/POST/PATCH /admin/roles`, `…/desactiver` |
| `/administration/habilitations` | idem | 12 · onglet « Rôles et habilitations » (matrice rôle × permission) | `GET /admin/permissions`, `PATCH /admin/roles/{id}` |
| `/administration/delegations` | idem | 12 · onglet « Délégations » | `GET /admin/delegations`, `GET /admin/absences` |
| `/administration/organisation` | idem | périmètres | `GET/POST/PATCH /admin/unites` |
| `/administration/securite` | idem | paramètres de sécurité | `GET/PATCH /admin/parametres-securite`, `GET /admin/signalements-telephone` |
| `/journal` | `(app)` | 13 · Journal d'audit | `GET /audit/indicateurs`, `GET /audit/evenements`, `GET /audit/export.xlsx`, `POST /audit/controles` |
| `/console` | `(console)` | 18 · Console FYXOP (partie établissements) | `GET /plateforme/etablissements` |
| `/console/etablissements/[id]` | `(console)` | — | `GET/PATCH /plateforme/etablissements/{id}`, `POST …/administrateurs` |
| `/console/journal` | `(console)` | — | `GET /plateforme/audit` |

Les onglets « Comptes externes à valider » et « Destinataires externes » de l'écran 12 ne sont **pas** affichés au S1 (S2 et S3).

### 7.2 Comportements à reproduire (relevés dans le prototype)

- **Layout `(auth)`** : deux colonnes. À gauche, un panneau sombre avec « ALPHA », le slogan « Chaque décision, formalisée, tracée et vérifiable. », un texte d'accroche et trois promesses (« Double authentification · Application Authenticator », « Journal infalsifiable · Chaque action tracée », « Données cloisonnées · Par établissement »). À droite, le formulaire. Sur mobile, une seule colonne avec le panneau réduit.
- **Connexion** : « Connexion », « Accédez à l'espace de votre établissement. », champs « Adresse e-mail professionnelle » et « Mot de passe », lien « Mot de passe oublié ? », bouton « Continuer » ; liens « Client ou fournisseur ? Accéder au portail externe » (désactivé au S1), « Vous avez reçu une invitation ? Activer mon compte », « Confidentialité et CGU », « Support », « Console FYXOP ». L'étape MFA affiche 6 cases `.otp` (Plex Mono 24 px, 52×60), avec saisie automatique, collage et `autocomplete="one-time-code"`, et un lien « Utiliser un code de secours ».
- **Activation** : onglets « Première connexion » / « Téléphone perdu » ; stepper « Mot de passe → Téléphone → Vérification » ; message « Bienvenue, {prénom} » ; champs « Nouveau mot de passe », « Confirmer le mot de passe » ; aide « 12 caractères minimum. Évitez votre nom et votre date de naissance. » ; « Continuer » ; « ← Retour à la connexion ». L'étape Téléphone affiche le QR, le secret en Mono par groupes de 4, et des liens vers Google ou Microsoft Authenticator. Après vérification, les 10 codes de secours sont affichés avec « Copier », « Télécharger » et la case « J'ai conservé mes codes ».
- **Coquille `(app)`** : barre latérale sombre avec le logo « ALPHA » et le nom de l'établissement, puis des groupes en capitales (« Gestion interne », « Administration », « Suivi et traçabilité », « Moi ») ; compteurs par entrée (`.cnt`) ; lien « Aide en ligne » ; pied avec initiales, nom et rôle. Bandeau supérieur : recherche (« Rechercher un dossier, un client, un NINEA… », inactive au S1), cloche avec compteur (`/moi/notifications`), aide « ? ». **Menu calculé** depuis `Moi.permissions` et `Moi.modules` (`lib/permissions.ts`) : au S1, « À traiter », « Administration » (si `admin.*`), « Journal d'audit » (si `audit.lecture`), « Mon compte ». Sur mobile, la barre latérale devient un tiroir (« Menu »).
- **À traiter** : titre « Bonjour {prénom}, voici ce qui vous attend » ; sous-titre « {Établissement} · tout ce qui attend votre décision, quel que soit le module. Les plus urgents en premier. » ; trois tuiles (En retard, Aujourd'hui, Cette semaine) ; puces de filtre par module avec compteurs (« Tout 9 », « Décisions internes 3 », …) ; sections groupées « En retard · 1 », « Aujourd'hui · 3 », « Cette semaine · 3 », « Plus tard · 2 » ; chaque ligne affiche le module, `référence · titre`, le montant en Mono (`14 600 000 FCFA`), le sous-titre, l'échéance (rouge si en retard : « En retard d'1 jour » ; ambre aujourd'hui) et un bouton d'action (« Décider », « Signer », « Valider », « Traiter ») vers `lien`. Badge « par délégation de … » le cas échéant. Encart final : « Vous serez absent ? Programmez une délégation dans Mon compte : vos demandes iront à votre délégataire pendant cette période. » État vide : « Rien à traiter pour le moment. » Actualisation des compteurs toutes les 60 s (avec `X-Alpha-Fond`).
- **Mon compte** : onglets « Profil », « Sécurité », « Absences et délégation », « Notifications ».
  - Profil : « Nom complet » (prénom + nom), « E-mail professionnel » (lecture seule), « Téléphone mobile », « Langue » (Français / English ; seul le français est traduit au S1), encadré « Rôle : … · Périmètre : … Le rôle et le périmètre sont attribués par l'administrateur. Pour les changer, adressez-lui une demande. », bouton « Enregistrer ».
  - Sécurité : mot de passe (changement), Authenticator (statut, date, « Changer de téléphone »), codes de secours (« 7 sur 10 restants », « Régénérer »), « J'ai perdu mon téléphone » (confirmation explicite), tableau « Appareils et sessions » (Appareil, Adresse IP, Ouverte le, Dernière activité, badge « Cette session », « Déconnecter ») et « Déconnecter les autres appareils ».
  - Absences et délégation : formulaire (Du, Au, Motif, Délégataire avec recherche, Commentaire), liste avec badge de statut (Soumise ambre, Validée vert, Refusée rouge, Annulée gris), section « Délégations reçues ».
  - Notifications : interrupteurs E-mail, Téléphone (notification), SMS, Résumé quotidien + heure ; mention « Les alertes de sécurité sont toujours envoyées par e-mail. » ; avertissement « Envoi par SMS et notification mobile disponible prochainement ».
- **Utilisateurs et rôles** : titre « Utilisateurs et rôles », sous-titre « {Établissement} · comptes, catalogue des rôles, habilitations, délégations de pouvoirs et destinataires externes. », bouton « + Inviter un utilisateur » ; recherche « Nom, e-mail… » ; filtre « Tous les rôles » (catalogue) ; colonnes **Utilisateur** (pastille d'initiales, nom, e-mail), **Rôle**, **Périmètre**, **Authenticator** (Activée / Non configurée / Suspendue), **Dernière connexion** (Mono, `10/10 08:02` ou `—`), **Statut** (Actif / Invité / Suspendu / Verrouillé), action « Modifier ». Bloc final « Historique des décisions · Utilisateurs et comptes · N décisions » (Date, Référence, Objet, Décision, Décidé par), « Les 3 dernières décisions. Rien n'est supprimé ni modifiable. »
- **Catalogue des rôles** : tableau (Libellé, Description, Titulaires, badge « Vacant » ambre si 0, Actif, Système) ; création et modification dans un panneau latéral.
- **Journal d'audit** : titre et sous-titre « {Établissement} · toutes les actions, en ajout seul : aucune entrée ne peut être modifiée ni supprimée, y compris par un administrateur. » ; bouton « Exporter (Excel) » (si `audit.export`) ; carte d'intégrité (« Intégrité vérifiée · Chaîne d'empreintes intacte · contrôle {date} », en vert, ou rouge « Chaîne rompue à l'événement n° … ») ; tuiles « Événements aujourd'hui », « Connexions échouées (24 h) », « Actions d'administration » ; recherche « Utilisateur, dossier, adresse IP… » ; filtre de catégorie (Toutes les actions, Connexions, Décisions, Modifications de données, Paramétrage, Accès API) ; période (Aujourd'hui, 7 derniers jours, 30 derniers jours) ; colonnes **Horodatage** (`10/10 20:31:07`, Mono), **Utilisateur**, **Action**, **Objet**, **Détail (avant → après)**, **Adresse IP** (Mono), **Empreinte** (`a41f…9c2e`, Mono, empreinte complète au survol et copiable) ; défilement infini par curseur.
- **Console FYXOP** : liste des établissements (Code, Raison sociale, Type, Statut, Utilisateurs actifs, Dernière activité, Intégrité du journal), bouton « + Nouvel établissement » ; bandeau permanent « Console FYXOP · aucun accès au contenu des dossiers ».

### 7.3 Charte

Polices via `next/font/google` : **IBM Plex Sans** (400, 500, 600, 700) pour le texte, **IBM Plex Mono** (400, 500, 600) pour les références, montants (alignés à droite), horodatages, adresses IP, empreintes, cases OTP, secrets et codes de secours.

Jetons relevés dans le CSS du prototype (`src/app/globals.css`, repris dans `tailwind.config.ts`) :

| Jeton | Valeur | Usage dans le prototype |
|---|---|---|
| `--encre` | `#0F172A` | texte principal, bouton primaire, fond de la barre latérale |
| `--marque` | `#1E3A8A` | survol du bouton primaire, entrée de menu active (`.nv-on`), focus des champs |
| `--fond` | `#F1F4F8` | fond de page |
| `--surface` | `#FFFFFF` | cartes, champs |
| `--bordure` | `#E2E8F0` | bordure des cartes et des en-têtes de tableau |
| `--bordure-champ` | `#808B9C` | champs, bouton secondaire |
| `--ligne` | `#EEF2F6` | séparateurs de lignes de tableau |
| `--entete-tableau` | `#F8FAFC` | fond des `th` |
| `--survol` | `#F1F5F9` | survol du bouton secondaire |
| `--texte-2` | `#334155` | libellés (`.lbl`), compteurs |
| `--texte-attenue` | `#475569` | onglets inactifs, `th` |
| `--texte-discret` | `#94A3B8` | titres de groupes du menu |
| `--menu-texte` | `#CBD5E1` | entrées de menu inactives |
| `--succes` / survol | `#15803D` / `#166534` | bouton de validation (`.btn-g`) |
| `--danger-texte` | `#B91C1C` | « En retard » |
| `--alerte-texte` | `#A16207` (et `#B45309`) | « Aujourd'hui », contour `:focus-visible` |
| `--accent` | `#FBBF24` | logo ALPHA |
| `--desactive` | `#CBD5E1` / texte `#475569` | `.btn-off` |
| Badges | vert `#DCFCE7`/`#14532D`, ambre `#FEF3C7`/`#78350F`, rouge `#FEE2E2`/`#7F1D1D`, bleu `#DBEAFE`/`#1E3A8A` | statuts |

Composants (mesures du prototype) : boutons hauteur 40 px (44 px sur les écrans d'authentification), rayon 8 px, police 600 14–15 px ; champs hauteur 42 px (44 px en authentification), rayon 8 px ; cartes avec rayon 10 px et bordure `--bordure` ; `th` 12 px en capitales, `letter-spacing .04em` ; `td` 14 px, padding 11×12 ; badges en pilule, 12 px, 600 ; onglets soulignés de 2 px. Focus visible obligatoire (`outline 2px #A16207`). Responsive : tableaux en défilement horizontal **dans** la carte sous 768 px, jamais la page entière. Interface en français ; dates `fr-SN` (`dd/MM HH:mm`), montants `14 600 000 FCFA` (espace fine insécable).

### 7.4 Client d'API

- `lib/api/client.ts` : `fetch` avec `credentials: "include"`, en-tête `X-CSRFToken` lu dans le cookie `alpha_csrf` pour toute méthode non sûre, conversion des erreurs `{code, message, details}` en `ApiError`. Sur 401 `SESSION_EXPIREE`, redirection vers `/connexion?suivant=<route>` ; sur 403, page « Accès refusé ».
- Types générés : `npm run api:types` = `openapi-typescript http://backend:8000/api/v1/schema/ -o src/lib/api/schema.d.ts` (fichier versionné, régénéré en CI pour détecter les écarts).
- TanStack Query pour toutes les lectures ; formulaires avec react-hook-form + zod (messages en français).
- `middleware.ts` : redirige vers `/connexion` toute route `(app)` ou `(console)` sans cookie `alpha_sid` (contrôle de confort ; la vraie vérification est faite par `GET /auth/session` dans le layout).
- Les composants qui lisent l'API sont des composants client (sessions par cookie, même origine) ; aucun secret côté serveur Next.

---

