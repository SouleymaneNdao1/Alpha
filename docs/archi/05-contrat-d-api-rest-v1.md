<!-- Généré depuis docs/architecture-sprint1.md -->
## 5. Contrat d'API REST v1


Base : `/api/v1`. JSON UTF-8. Schéma OpenAPI généré par drf-spectacular : `/api/v1/schema/` ; Swagger : `/api/v1/docs/` (dev et recette uniquement au S1).

**Erreurs** : `{"code": "IDENTIFIANTS_INVALIDES", "message": "Adresse e-mail ou mot de passe incorrect.", "details": {...}}`. Erreurs de validation : 400 `VALIDATION`, `details = {"champ": ["message"]}`. Codes HTTP : 400, 401 (non authentifié / session expirée), 403 (permission), 404 (inexistant **ou autre établissement** : jamais 403 pour un objet d'un autre tenant), 409 (conflit métier), 410 (jeton), 423 (verrouillage / lecture seule), 429 (débit).

**Pagination** : `?page=1&taille=25` (max 100) → `{count, next, previous, results}` ; journal d'audit en curseur `?curseur=` → `{next, results}`.

**Permissions** : `Anonyme` ; `Session` = utilisateur d'établissement authentifié avec MFA ; `Perm(x)` = Session + code `x` dans l'un de ses rôles actifs ; `StepUp` = code TOTP requis dans le corps ; `SuperAdmin` = session plateforme.

### 5.1 Objets de référence

```jsonc
// Moi
{ "id": "uuid", "prenom": "Abdou", "nom": "Kane", "initiales": "AK", "email": "a.kane@etablissement-demo.sn",
  "telephone_mobile": "+221770000000", "langue": "fr",
  "etablissement": { "id": "uuid", "raison_sociale": "Établissement démo", "type": "BANQUE", "statut": "ACTIF" },
  "role_principal": { "id": "uuid", "libelle": "DAF", "unite": "Direction administrative et financière" },
  "affectations": [ { "role": {"id": "uuid", "libelle": "DAF"}, "unite": {"id": "uuid", "libelle": "…"} | null, "principal": true } ],
  "permissions": ["audit.lecture"], "modules": ["COMPTE", "ADMINISTRATION"],
  "signature_bloquee": false, "inactivite_session_min": 15, "est_super_admin": false }

// UtilisateurListe (admin)
{ "id": "uuid", "prenom": "Awa", "nom": "Diop", "initiales": "AD", "email": "a.diop@…",
  "role_principal": "Analyste crédit", "perimetre": "Dakar-Plateau · crédit particuliers",
  "authenticator": "ACTIVE" | "NON_CONFIGUREE" | "SUSPENDUE",
  "derniere_connexion": "2026-10-10T08:02:00Z" | null,
  "statut": "ACTIF" | "INVITE" | "SUSPENDU" | "DESACTIVE", "verrouille": false }

// Role
{ "id": "uuid", "code": "analyste-credit", "libelle": "Analyste crédit", "description": "…",
  "permissions": [], "est_systeme": false, "actif": true, "ordre": 2, "nb_titulaires": 3, "vacant": false }

// Tache
{ "id": "uuid", "module": "INTERNE", "module_libelle": "Décisions internes", "reference": "ED-2026-0077",
  "titre": "40 postes informatiques", "sous_titre": "demandé par Babacar Diouf",
  "montant": "14600000.00", "devise": "XOF", "action": "DECIDER", "action_libelle": "Décider",
  "type_echeance": "AVANT", "echeance": "2026-10-14T23:59:59Z",
  "groupe": "EN_RETARD" | "AUJOURDHUI" | "CETTE_SEMAINE" | "PLUS_TARD",
  "retard_jours": 1, "lien": "/…", "par_delegation_de": null | { "id": "uuid", "nom": "Mamadou Sow" } }

// EvenementAudit
{ "seq": 1284, "horodatage": "2026-10-10T20:31:07.123456Z", "acteur_type": "UTILISATEUR", "acteur_libelle": "Awa Diop",
  "categorie": "DECISION", "action": "…", "action_libelle": "Décision", "objet_type": "…", "objet_id": "…",
  "objet_libelle": "CR-2026-0412", "avant": {"avis": null}, "apres": {"avis": "favorable sous condition"},
  "detail": "Avis : — → favorable sous condition", "ip": "10.20.4.17", "hash": "a41f…", "hash_court": "a41f…9c2e" }
```

### 5.2 Authentification (`/auth`)

| Méthode | Chemin | Corps | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/auth/csrf` | — | 204 (cookie `alpha_csrf`) | Anonyme |
| GET | `/auth/session` | — | 200 `Moi` · 401 | Anonyme |
| POST | `/auth/connexion` | `{email, mot_de_passe}` | 200 `{etape: "MFA_REQUIS" \| "REENROLEMENT_REQUIS"}` · 401 `IDENTIFIANTS_INVALIDES` · 403 `ETABLISSEMENT_SUSPENDU` · 429 | Anonyme |
| POST | `/auth/mfa` | `{code}` ou `{code_secours}` | 200 `{utilisateur: Moi, codes_secours_restants}` · 401 `CODE_INVALIDE {tentatives_restantes}` · 401 `PREAUTH_EXPIREE` · 423 `COMPTE_VERROUILLE {jusqua}` | Pré-auth |
| POST | `/auth/deconnexion` | — | 204 | Session |
| GET | `/auth/activation/{jeton}` | — | 200 `{prenom, etablissement, role, etape}` · 410 | Anonyme |
| POST | `/auth/activation/{jeton}/mot-de-passe` | `{mot_de_passe, confirmation}` | 204 · 400 `VALIDATION` | Anonyme |
| POST | `/auth/activation/{jeton}/authenticator` | — | 200 `{qr_svg, secret_affichable, emetteur, compte}` · 409 `ETAPE_INVALIDE` | Anonyme |
| POST | `/auth/activation/{jeton}/authenticator/confirmer` | `{code}` | 200 `{codes_secours: [10]}` · 401 `CODE_INVALIDE` | Anonyme |
| POST | `/auth/activation/{jeton}/terminer` | `{codes_conserves: true}` | 200 `Moi` (session ouverte) | Anonyme |
| GET | `/auth/reenrolement/{jeton}` | — | 200 `{prenom, etablissement}` · 410 | Anonyme |
| POST | `/auth/reenrolement/{jeton}/mot-de-passe` | `{mot_de_passe}` (vérifie l'actuel) | 204 · 401 | Anonyme |
| POST | `/auth/reenrolement/{jeton}/authenticator` | — | comme activation | Anonyme |
| POST | `/auth/reenrolement/{jeton}/authenticator/confirmer` | `{code}` | 200 `{codes_secours}` | Anonyme |
| POST | `/auth/reenrolement/{jeton}/terminer` | `{codes_conserves: true}` | 200 `Moi` | Anonyme |
| POST | `/auth/mot-de-passe/oubli` | `{email}` | 202 | Anonyme |
| GET | `/auth/mot-de-passe/reinitialisation/{jeton}` | — | 200 `{email_masque}` · 410 | Anonyme |
| POST | `/auth/mot-de-passe/reinitialisation/{jeton}` | `{mot_de_passe, confirmation, code \| code_secours}` | 204 · 400 · 401 `CODE_INVALIDE` · 410 | Anonyme |
| POST | `/auth/telephone-perdu` | `{email, mot_de_passe}` | 202 | Anonyme |

### 5.3 Mon compte (`/moi`)

| Méthode | Chemin | Corps | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/moi` | — | 200 `Moi` | Session |
| PATCH | `/moi` | `{prenom?, nom?, telephone_mobile?, langue?}` (e-mail non modifiable) | 200 `Moi` | Session |
| POST | `/moi/mot-de-passe` | `{actuel, nouveau, confirmation, code}` | 204 · 400 · 401 | Session + StepUp |
| GET | `/moi/securite` | — | 200 `{authenticator: {statut, libelle, active_le}, codes_secours_restants, signature_bloquee, signalement: {statut, signale_le} \| null, mdp_modifie_le}` | Session |
| POST | `/moi/authenticator/changement` | `{code_actuel}` | 200 `{qr_svg, secret_affichable}` | Session + StepUp |
| POST | `/moi/authenticator/changement/confirmer` | `{code_nouveau}` | 204 · 401 | Session |
| POST | `/moi/codes-secours` | `{code}` | 200 `{codes_secours: [10]}` | Session + StepUp |
| POST | `/moi/telephone-perdu` | `{}` | 202 (la session est révoquée) | Session |
| GET | `/moi/sessions` | — | 200 `[{id, appareil, ip, methode_mfa, cree_le, derniere_activite, courante}]` | Session |
| DELETE | `/moi/sessions/{id}` | — | 204 · 404 | Session |
| POST | `/moi/sessions/revoquer-autres` | — | 200 `{revoquees: n}` | Session |
| GET | `/moi/absences` | `?statut=` | 200 page `[Absence + delegation]` | Session |
| POST | `/moi/absences` | `{debut, fin, motif, commentaire?, delegataire_id, role_id?}` | 201 · 400 · 409 `CHEVAUCHEMENT` | Session |
| POST | `/moi/absences/{id}/annuler` | — | 200 | Session (avant `debut` ; ensuite, `fin` est avancée à maintenant) |
| GET | `/moi/delegataires-possibles` | `?q=` | 200 `[{id, nom, role_principal}]` (actifs, même établissement, hors soi) | Session |
| GET | `/moi/delegations-recues` | — | 200 `[{delegant, role, debut, fin, statut}]` | Session |
| GET | `/moi/preferences-notification` | — | 200 `{email, push, sms, resume_quotidien, heure_resume}` | Session |
| PUT | `/moi/preferences-notification` | idem | 200 | Session |
| GET | `/moi/notifications` | `?non_lues=1` | 200 page `[{id, type, titre, corps, lien, lue_le, cree_le}]` + `non_lues` | Session |
| POST | `/moi/notifications/{id}/lue` · `/moi/notifications/tout-lu` | — | 204 | Session |

### 5.4 À traiter (`/taches`) et absences

| Méthode | Chemin | Corps / paramètres | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/taches` | `?module=&groupe=&q=&page=` | 200 page `Tache` triée (groupe, échéance) | Session |
| GET | `/taches/compteurs` | — | 200 `{total, par_groupe: {EN_RETARD, AUJOURDHUI, CETTE_SEMAINE, PLUS_TARD}, par_module: {INTERNE: 3, …}}` | Session |
| GET | `/taches/{id}` | — | 200 `Tache` · 404 si non visible | Session |
| GET | `/absences/{id}` | — | 200 | Session (demandeur, valideur ou `admin.absences`) |
| POST | `/absences/{id}/valider` | `{}` | 200 ; délégation `ACTIVE` ; tâche terminée ; notifications demandeur + délégataire | valideur désigné ou `admin.absences` |
| POST | `/absences/{id}/refuser` | `{motif}` | 200 | idem |

### 5.5 Administration de l'établissement (`/admin`)

| Méthode | Chemin | Corps / paramètres | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/admin/utilisateurs` | `?q=&role_id=&statut=&page=` | 200 page `UtilisateurListe` | `admin.utilisateurs` |
| POST | `/admin/utilisateurs` | `{email, prenom, nom, role_id, unite_id?, responsable_id?, telephone_mobile?}` | 201 · 400 `ROLE_HORS_CATALOGUE` · 409 `EMAIL_EXISTE` | `admin.utilisateurs` |
| GET | `/admin/utilisateurs/{id}` | — | 200 détail + affectations + sessions actives + signalement | `admin.utilisateurs` |
| PATCH | `/admin/utilisateurs/{id}` | `{prenom?, nom?, telephone_mobile?, responsable_id?}` | 200 | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/affectations` | `{role_id, unite_id?, principal}` | 201 · 409 | `admin.utilisateurs` |
| POST | `/admin/affectations/{id}/terminer` | — | 200 · 409 `DERNIER_ADMINISTRATEUR` | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/suspendre` | `{motif}` | 200 (sessions révoquées) · 409 `DERNIER_ADMINISTRATEUR` | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/reactiver` | — | 200 | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/deverrouiller` | — | 200 | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/renvoyer-invitation` | — | 202 · 409 si non `INVITE` | `admin.utilisateurs` |
| POST | `/admin/utilisateurs/{id}/sessions/revoquer` | — | 200 | `admin.utilisateurs` |
| GET | `/admin/utilisateurs/historique` | `?limite=3` | 200 `[EvenementAudit]` (actions d'administration sur les comptes) | `admin.utilisateurs` |
| GET | `/admin/signalements-telephone` | `?statut=OUVERT` | 200 page | `admin.utilisateurs` |
| POST | `/admin/signalements-telephone/{id}/reinitialiser` | `{mode_verification, commentaire, code}` | 200 · 403 `AUTO_TRAITEMENT_INTERDIT` | `admin.utilisateurs` + StepUp |
| POST | `/admin/signalements-telephone/{id}/annuler` | `{commentaire}` (téléphone retrouvé : réactive l'Authenticator) | 200 | `admin.utilisateurs` + StepUp |
| GET | `/admin/roles` | `?actif=` | 200 `[Role]` | `admin.roles` ou `admin.utilisateurs` (lecture) |
| POST | `/admin/roles` | `{libelle, code?, description?, permissions?, ordre?}` | 201 · 409 `LIBELLE_EXISTE` | `admin.roles` |
| PATCH | `/admin/roles/{id}` | `{libelle?, description?, permissions?, ordre?}` | 200 · 409 `ROLE_SYSTEME` | `admin.roles` |
| POST | `/admin/roles/{id}/desactiver` · `/activer` | — | 200 · 409 `ROLE_SYSTEME` | `admin.roles` |
| GET | `/admin/permissions` | — | 200 `[{code, libelle, description}]` | `admin.roles` |
| GET | `/admin/unites` | — | 200 arbre `[{id, type, code, libelle, enfants: [...]}]` | `admin.organisation` ou `admin.utilisateurs` (lecture) |
| POST | `/admin/unites` · PATCH `/admin/unites/{id}` | `{parent_id?, type, code, libelle, actif?}` | 201/200 | `admin.organisation` |
| GET | `/admin/delegations` | `?statut=&du=&au=` | 200 page | `admin.utilisateurs` ou `admin.absences` |
| GET | `/admin/absences` | `?statut=SOUMISE` | 200 page | `admin.absences` |
| GET | `/admin/parametres-securite` | — | 200 `ParametresEtablissement` | `admin.securite` |
| PATCH | `/admin/parametres-securite` | champs de 2.2 + `code` | 200 · 400 (bornes) | `admin.securite` + StepUp |

### 5.6 Journal d'audit (`/audit`)

| Méthode | Chemin | Paramètres | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/audit/evenements` | `?q=` (utilisateur, objet, IP) `&categorie=CONNEXION,DECISION,MODIFICATION,PARAMETRAGE,ACCES_API&periode=aujourdhui\|7j\|30j&du=&au=&acteur_id=&objet_type=&objet_id=&curseur=` | 200 curseur `[EvenementAudit]` (horodatage décroissant) | `audit.lecture` |
| GET | `/audit/indicateurs` | — | 200 `{evenements_aujourdhui, connexions_echouees_24h, actions_administration_24h, dernier_controle: {statut, lance_le, dernier_seq}}` | `audit.lecture` |
| GET | `/audit/export.xlsx` | mêmes filtres (max 100 000 lignes) | 200 fichier ; l'export lui-même est journalisé (`audit.export`) | `audit.export` |
| GET | `/audit/controles` | — | 200 page `ControleIntegriteAudit` | `audit.lecture` |
| POST | `/audit/controles` | — | 202 `{id}` (lancement asynchrone) | `audit.lecture` |

### 5.7 Console FYXOP (`/plateforme`)

| Méthode | Chemin | Corps | Réponses | Perm. |
|---|---|---|---|---|
| GET | `/plateforme/etablissements` | `?q=&statut=` | 200 `[{id, code, raison_sociale, type, statut, cree_le, stats: {nb_utilisateurs_actifs, nb_invites, derniere_activite, dernier_controle_statut}}]` | SuperAdmin |
| POST | `/plateforme/etablissements` | `{code, raison_sociale, type, pays, administrateur: {email, prenom, nom}}` | 201 (provisionnement + invitation) · 409 | SuperAdmin + StepUp |
| GET | `/plateforme/etablissements/{id}` | — | 200 (métadonnées + stats, aucun contenu) | SuperAdmin |
| PATCH | `/plateforme/etablissements/{id}` | `{raison_sociale?, statut?}` | 200 | SuperAdmin + StepUp |
| POST | `/plateforme/etablissements/{id}/administrateurs` | `{email, prenom, nom}` | 201 (invitation sur le rôle « Administrateur ALPHA ») | SuperAdmin + StepUp |
| GET | `/plateforme/audit` | comme `/audit/evenements` | chaîne plateforme | SuperAdmin |
| GET | `/plateforme/moi` | — | 200 | SuperAdmin |

---

