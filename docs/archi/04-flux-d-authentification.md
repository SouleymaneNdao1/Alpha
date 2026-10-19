<!-- Généré depuis docs/architecture-sprint1.md -->
## 4. Flux d'authentification


### 4.1 Choix : session par cookie httpOnly + CSRF (pas de JWT)

Le seul client du sprint 1 est le navigateur, servi sur la **même origine** que l'API. Un cookie de session httpOnly n'est pas lisible par JavaScript (donc pas volable par XSS) et la révocation côté serveur est immédiate, ce qu'exigent « téléphone perdu », « appareils et sessions » et l'expiration d'inactivité. Avec un JWT, il faudrait une liste de révocation et des jetons de rafraîchissement, donc un état serveur, avec plus de surface d'attaque. Les intégrations machine (Core Banking, S4) auront leur propre authentification (clés API ou OAuth 2.0 client credentials) via une classe DRF séparée.

Paramètres : cookie `alpha_sid` (`HttpOnly`, `Secure` hors dev, `SameSite=Lax`, `Path=/`), `SESSION_ENGINE="django.contrib.sessions.backends.cached_db"`, `SESSION_EXPIRE_AT_BROWSER_CLOSE=True` ; cookie `alpha_csrf` (lisible par JS, `SameSite=Lax`), en-tête `X-CSRFToken`. Les vues anonymes de `/auth/` sont décorées `csrf_protect` (protection contre le login CSRF) ; `GET /auth/csrf` pose le cookie.

### 4.2 Connexion + MFA

1. Le front appelle `GET /auth/csrf`, puis `POST /auth/connexion {email, mot_de_passe}`.
2. Limitation de débit Redis : 10/min par IP et 20/h par e-mail (clé = HMAC de l'e-mail). Dépassement → 429.
3. `alpha_resoudre_connexion(email)`. E-mail inconnu → hachage Argon2 factice (temps constant), audit `auth.connexion.echec` dans la **chaîne plateforme** (acteur `ANONYME`, objet = e-mail masqué `m.sow@…`), réponse 401 `IDENTIFIANTS_INVALIDES`.
4. `contexte_tenant(etab)` ; chargement de l'utilisateur. Refus avec la **même réponse 401** si : statut ≠ `ACTIF`, `verrouille_jusqua > now`, `bloque_par_admin`, établissement `SUSPENDU` (dans ce dernier cas, 403 `ETABLISSEMENT_SUSPENDU`, car l'utilisateur doit savoir que l'accès est coupé).
5. Vérification Argon2. Échec → `echecs_connexion += 1` ; à `tentatives_max` (5) : `verrouille_jusqua = now + 15 min`, `verrouillages_24h += 1`, e-mail d'alerte « compte verrouillé » ; au 3e verrouillage en 24 h : `bloque_par_admin = true`. Audit `auth.connexion.echec` (motif `MOT_DE_PASSE`) ou `auth.verrouillage`. Réponse 401.
6. Succès du mot de passe → la session reçoit l'état **pré-authentifié** : `preauth = {user_id, tenant_id, scope, expire: now+5min, essais_mfa: 0}`. Aucun `login()` Django à ce stade. Si `mfa_a_reconfigurer` → réponse `{etape: "REENROLEMENT_REQUIS"}` (l'utilisateur doit passer par le lien de réenrôlement, 4.5). Sinon → `200 {etape: "MFA_REQUIS"}`.
7. `POST /auth/mfa {code}` (6 chiffres) **ou** `{code_secours}`. Limite 5/min par session.
8. Vérification TOTP : `pyotp.TOTP(secret).verify` avec fenêtre ±1 pas ; on calcule le compteur accepté et on refuse s'il est `≤ dernier_pas` (anti-rejeu), sinon `dernier_pas = compteur`. Un Authenticator `SUSPENDU` (téléphone perdu) est refusé ; seuls les codes de secours restent utilisables.
9. Code de secours : normalisation (majuscules, sans tiret ni espace), recherche par `code_hmac` parmi les codes non utilisés et non invalidés, puis `utilise_le = now` (`SELECT … FOR UPDATE`). Audit `mfa.code_secours_utilise` ; e-mail d'information ; s'il reste ≤ 2 codes, le front invite à les régénérer.
10. Échec → compte dans `echecs_connexion` (même verrouillage qu'en 5), audit `auth.connexion.echec` (motif `MFA`, objet = e-mail masqué) ; réponse 401 `CODE_INVALIDE {tentatives_restantes}` ; à 0 → 423 `COMPTE_VERROUILLE {jusqua}` et la pré-authentification est effacée.
11. Succès → `request.session.cycle_key()` (anti-fixation), `login()`, `session["tenant_id"]`, `session["scope"]="tenant"` (ou `platform`), `session["mfa_le"]=now`, création de `session_appareil`, remise à zéro de `echecs_connexion`, `derniere_connexion=now`. Audit `auth.connexion.succes` (« Connexion réussie · double authentification OK »).
12. **Connexion inhabituelle** : si aucun `session_appareil` des 90 derniers jours n'a la même famille navigateur + OS **et** le même préfixe IP /16 → e-mail « Nouvelle connexion à votre compte ALPHA » (appareil, IP, heure, lien « Ce n'était pas moi » vers `/activation?onglet=telephone-perdu`) et audit `SECURITE`.
13. Réponse `200 {utilisateur: Moi}` ; le front redirige vers `/a-traiter` (ou `/console` pour un super-admin).

### 4.3 Activation du compte par invitation

1. L'administrateur appelle `POST /admin/utilisateurs {email, prenom, nom, role_id, unite_id?, responsable_id?, telephone_mobile?}`. Le rôle doit être actif et appartenir au catalogue de l'établissement (sinon 400 `ROLE_HORS_CATALOGUE`).
2. Création de `utilisateur` (statut `INVITE`, mot de passe inutilisable), de l'`affectation_role` principale et de `preferences_notification` par défaut ; jeton `INVITATION` valable `validite_invitation_h` (72 h). Audit `utilisateur.invite`. E-mail (après commit) avec le lien `https://app/activation?jeton=<jeton>`.
3. `GET /auth/activation/{jeton}` → `alpha_resoudre_jeton` → contexte tenant → `200 {prenom, etablissement, role, etape}` (« Bienvenue, Cheikh. L'administrateur de l'Établissement démo vous a invité comme Analyste crédit »). Jeton invalide ou expiré → 410 `JETON_INVALIDE`.
4. **Étape « Mot de passe »** : `POST /auth/activation/{jeton}/mot-de-passe {mot_de_passe, confirmation}` → politique (4.9) → hachage Argon2 enregistré, `jeton.etape = MDP_OK`. Le compte reste `INVITE` (non utilisable) tant que le MFA n'est pas confirmé.
5. **Étape « Téléphone »** : `POST /auth/activation/{jeton}/authenticator` → génération d'un secret base32 de 160 bits, `authenticator_totp` en `EN_ATTENTE` (secret chiffré), retour `{qr_svg, secret_affichable: "JBSW Y3DP …", emetteur: "ALPHA (Établissement démo)"}`. L'URI `otpauth://totp/ALPHA%20(Établissement%20démo):c.badiane@…?secret=…&issuer=…&digits=6&period=30` est encodé en QR SVG (segno) côté serveur ; le secret n'est **jamais** journalisé. Rappeler l'appel régénère le secret (l'ancien en attente est révoqué).
6. **Étape « Vérification »** : `POST /auth/activation/{jeton}/authenticator/confirmer {code}` → vérification TOTP (5 essais, puis jeton annulé et nouvelle invitation nécessaire) → Authenticator `ACTIF`, génération de 10 codes de secours (lot), réponse `200 {codes_secours: [...]}`, affichés **une seule fois** (copie, téléchargement `.txt`, impression).
7. `POST /auth/activation/{jeton}/terminer {codes_conserves: true}` → `utilisateur.statut = ACTIF`, `active_le = now`, `jeton.utilise_le = now`, connexion ouverte comme en 4.2 (étapes 11 à 13). Audit `utilisateur.active` et `mfa.active`. Le front redirige vers `/a-traiter`.

### 4.4 Codes de secours

1. Génération : 10 codes `XXXX-XXXX` (`secrets.choice` sur l'alphabet Crockford), HMAC-SHA256 avec le poivre `ALPHA_HMAC_POIVRE` ; tout lot antérieur reçoit `invalide_le = now`.
2. Usage : uniquement à l'étape MFA de la connexion (4.2, étape 9) et comme preuve dans la réinitialisation de mot de passe (4.7). **Pas** pour la signature des décisions (S2).
3. Régénération par l'utilisateur : `POST /moi/codes-secours {code}` (step-up TOTP obligatoire) → 10 nouveaux codes affichés une fois. Audit `mfa.codes_regeneres`.
4. Mon compte affiche le nombre de codes restants, jamais les codes eux-mêmes.

### 4.5 Téléphone perdu

**Signalement** (bloque immédiatement la signature, CDC §4.6) :
1. Depuis la page publique (onglet « Téléphone perdu » de `/activation`) : `POST /auth/telephone-perdu {email, mot_de_passe}`. Limite 3/h par IP. Réponse toujours `202` (pas d'information sur l'existence du compte). Si le mot de passe est faux, on compte un échec (4.2, étape 5) et on ne fait rien d'autre.
   Depuis Mon compte (utilisateur connecté, ex. sur son PC) : `POST /moi/telephone-perdu`.
2. Transaction unique : `utilisateur.signature_bloquee = true` ; Authenticator `ACTIF` → `SUSPENDU` ; `signalement_telephone_perdu` `OUVERT` ; **toutes les sessions révoquées** (`motif_fin=TELEPHONE_PERDU`), y compris la session courante si le signalement vient de Mon compte ; tâche « À traiter » `module=ADMINISTRATION`, `action=TRAITER`, `assigne_role_id` = rôle(s) portant `admin.utilisateurs`, `titre="Téléphone perdu · <Nom>"`, `echeance = now + 1 jour ouvré`. Audit `telephone.signale` (catégorie `SECURITE`). E-mails à l'utilisateur et aux administrateurs.
3. Tant que le dossier est ouvert, l'utilisateur peut encore se connecter avec un **code de secours** pour consulter et travailler ; toute signature (S2) est refusée (`SIGNATURE_BLOQUEE`).

**Réinitialisation par l'administrateur après vérification d'identité** :
4. Un administrateur **autre que l'intéressé** vérifie l'identité hors ligne (présentiel avec pièce d'identité, rappel au numéro connu, visio), puis appelle `POST /admin/signalements-telephone/{id}/reinitialiser {mode_verification, commentaire, code_totp}` (step-up TOTP de l'administrateur). S'il n'existe pas d'autre administrateur : point ouvert P4 (super-admin FYXOP).
5. Effets : Authenticator `REVOQUE`, codes de secours invalidés, `mfa_a_reconfigurer = true`, signalement `REINITIALISE` (`traite_par_id`, `mode_verification`), tâche terminée, jeton `REENROLEMENT_MFA` de 24 h envoyé par e-mail. Audit `telephone.reinitialise` avec le mode de vérification.
6. **Réenrôlement** par l'utilisateur via `/reenrolement/{jeton}` : `POST /auth/reenrolement/{jeton}/mot-de-passe {mot_de_passe}` (vérification du mot de passe **actuel**, pas de définition), puis `…/authenticator`, `…/authenticator/confirmer`, `…/terminer`, comme les étapes 5 à 7 de 4.3. À la fin : `signature_bloquee = false`, `mfa_a_reconfigurer = false`, connexion ouverte. Audit `mfa.reenrole`.

**Changement de téléphone sans perte** (Mon compte) : `POST /moi/authenticator/changement {code_actuel}` → nouveau secret `EN_ATTENTE` + QR ; `POST /moi/authenticator/changement/confirmer {code_nouveau}` → ancien `REVOQUE`, nouveau `ACTIF` ; les codes de secours sont conservés. E-mail d'alerte. Audit `mfa.change`.

### 4.6 Déconnexion

`POST /auth/deconnexion` → `session_appareil.revoque_le = now` (`DECONNEXION`), `logout()`. Audit `auth.deconnexion`.

### 4.7 Réinitialisation du mot de passe

1. `POST /auth/mot-de-passe/oubli {email}` → toujours `202`. Limites : 3/h par e-mail, 10/h par IP. Si le compte existe et est `ACTIF` : jeton `REINIT_MDP` de 30 min (les précédents sont annulés), e-mail avec le lien `/reinitialisation/{jeton}`. Audit `auth.mdp.oubli_demande`.
2. `GET /auth/mot-de-passe/reinitialisation/{jeton}` → `200 {email_masque}` ou 410.
3. `POST /auth/mot-de-passe/reinitialisation/{jeton} {mot_de_passe, confirmation, code | code_secours}` → **preuve MFA exigée** : un accès à la seule boîte e-mail ne suffit pas. Sans Authenticator ni code de secours, il faut passer par « Téléphone perdu ».
4. Contrôle de la politique et de l'historique → mot de passe enregistré, entrée dans `historique_mot_de_passe`, `mdp_modifie_le`, **révocation de toutes les sessions** (`MDP_CHANGE`), remise à zéro du verrouillage, jeton consommé. E-mail « Votre mot de passe a été modifié ». Audit `auth.mdp.reinitialise`. Réponse 204 ; le front renvoie vers `/connexion`.

Changement volontaire dans Mon compte : `POST /moi/mot-de-passe {actuel, nouveau, confirmation, code}` → mêmes contrôles ; révoque les **autres** sessions.

### 4.8 Sessions, inactivité, appareils

`SessionActiviteMiddleware`, pour toute requête authentifiée :
1. Recherche du `session_appareil` par `sha256(session_key)` (cache Redis de 60 s).
2. Absent ou `revoque_le` renseigné → `flush()` et 401 `SESSION_EXPIREE`.
3. `now - derniere_activite > inactivite_session_min` → révocation `INACTIVITE`, audit `auth.session.expiree`, 401.
4. `now > expire_le` (durée max 12 h) → révocation `EXPIRATION`, 401.
5. Sinon, mise à jour de `derniere_activite`, au plus une écriture par minute.

Les appels de fond du front (compteurs de la boîte, notifications) envoient l'en-tête `X-Alpha-Fond: 1` et **ne prolongent pas** l'inactivité. Le front affiche un avertissement 60 s avant l'expiration (« Votre session va expirer », bouton « Rester connecté » = `GET /auth/session`).

### 4.9 Mot de passe et chiffrement

- `PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]` (Argon2id, paramètres par défaut de Django 5) ; aucun autre hacheur accepté.
- Validateurs : longueur ≥ 12 (`mdp_longueur_min`) ; au moins 3 catégories sur 4 (minuscule, majuscule, chiffre, symbole) ; `UserAttributeSimilarityValidator` sur prénom, nom et e-mail ; `CommonPasswordValidator` ; `NumericPasswordValidator` ; différent des 5 derniers (`historique_mot_de_passe`) ; refus des suites de 4 chiffres ressemblant à une année de naissance (`19xx`, `20xx`). Le front affiche « 12 caractères minimum. Évitez votre nom et votre date de naissance. » et l'avancement de chaque règle.
- Secret TOTP chiffré au repos : `MultiFernet` sur `ALPHA_CLES_CHIFFREMENT` (liste de clés base64 ; la première chiffre, toutes déchiffrent). `cle_version` permet la commande `manage.py rechiffrer_secrets`. Les clés ne sont jamais en base ni dans l'image (variables d'environnement / fichier secret Docker).
- Step-up TOTP (`alpha.core.permissions.StepUpTOTP`) : les actions sensibles exigent un champ `code` TOTP valide dans le corps (changement de téléphone, régénération des codes, changement de mot de passe, réinitialisation « téléphone perdu » par l'administrateur, paramètres de sécurité). Le même mécanisme servira à la signature des décisions (S2).

---

