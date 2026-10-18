# Recette et production sur le VPS : runbook

Tâche D3 (architecture § 1.3, § 8 et § 10). Ce document s'adresse à la personne qui installe et
exploite ALPHA sur le serveur. La surveillance est décrite à part, dans
[`monitoring.md`](monitoring.md).

Exigences du cahier des charges (section 5) couvertes ici :

| Exigence | Comment |
|---|---|
| Disponibilité 99,5 % | redémarrage automatique des conteneurs, déploiement avec retour automatique, surveillance externe ([`monitoring.md`](monitoring.md)) |
| TLS 1.2 minimum | Caddy : `protocols tls1.2 tls1.3`, certificats Let's Encrypt renouvelés seuls |
| Sauvegarde quotidienne chiffrée hors site | `alpha-sauvegarde@<env>.timer` → `scripts/sauvegarde.sh` (age + rclone), § 8 |
| Perte de données maximale 24 h (RPO) | une sauvegarde chaque nuit + une avant chaque déploiement ; alerte si la dernière a plus de 26 h |
| Reprise en moins de 4 h (RTO) | restauration scriptée et vérifiée (`scripts/restauration.sh`), plan de reprise § 11.8 |

Sommaire :
1. [Vue d'ensemble](#1-vue-densemble)
2. [Préparation du VPS](#2-préparation-du-vps)
3. [DNS](#3-dns)
4. [Secrets](#4-secrets)
5. [Premier déploiement](#5-premier-déploiement)
6. [Mise à jour](#6-mise-à-jour)
7. [Retour arrière](#7-retour-arrière)
8. [Sauvegarde et restauration](#8-sauvegarde-et-restauration)
9. [Accès à la console super-administrateur (P6)](#9-accès-à-la-console-super-administrateur-p6)
10. [Monitoring](#10-monitoring)
11. [Que faire si…](#11-que-faire-si)
12. [Différences entre recette et production](#12-différences-entre-recette-et-production)

---

## 1. Vue d'ensemble

Un seul VPS (Hostinger KVM 2 : 2 vCPU, 8 Go, 100 Go) porte la recette et la production pendant le
pilote. Trois projets compose **séparés**, chacun avec ses réseaux, ses volumes et ses secrets :

```
                      Internet (80, 443 tcp/udp)
                                │
                  ┌─────────────▼──────────────┐  projet alpha-proxy
                  │ Caddy (TLS, HSTS, CSP,     │  docker-compose.proxy.yml
                  │ en-têtes, liste d'IP P6)   │  .env.caddy
                  └──────┬───────────────┬─────┘
        réseau alpha-prod-web      réseau alpha-recette-web   (internes, sans Internet)
                         │               │
  projet alpha-prod      ▼               ▼      projet alpha-recette
  backend · frontend                     backend · frontend · mailpit
  worker · beat · migrate                worker · beat · migrate
  db · redis (réseau interne)            db · redis (réseau interne, aucun accès Internet)
  .env.prod                              .env.recette
```

- Caddy ne voit ni les bases ni Redis : il ne rejoint que les réseaux `*-web`.
- La recette n'a **aucun** accès à Internet (aucun e-mail réel ne peut partir, décision P11).
- En production, seuls `backend` et `worker` sortent (SMTP réel).
- `/api/*` est routé par Caddy vers Django, le reste vers Next.js, sur la même origine (cookies
  `SameSite=Lax`, pas de CORS). Les réécritures `/api` de Next sont figées au build et ne servent
  plus que de filet.
- Les **images** portent le code et sont étiquetées par version (`alpha-backend:v0.1.0`,
  `alpha-frontend:v0.1.0`) : la même image passe de la recette à la production, et revenir en
  arrière consiste à relancer l'image précédente. Les fichiers compose et le Caddyfile viennent
  de la copie du dépôt sur le VPS (`/opt/alpha`).

Budget mémoire (limites compose, § 1.3) :

| Projet | Limites cumulées |
|---|---|
| production | ≈ 4,5 Go (db 2 Go, backend 1 Go, worker 512 Mo, frontend 512 Mo, beat 256 Mo, redis 256 Mo) |
| recette | ≈ 2,1 Go |
| proxy | 256 Mo |
| système, sauvegardes, marge | ≈ 1,1 Go + 2 Go de swap |

Portabilité (P8 non tranché) : rien n'est propre à Hostinger. Tout Linux avec Docker Engine,
systemd et deux noms de domaine suffit ; pour séparer la production sur un VPS dédié, il suffit de
ne déployer que `prod` (et le proxy) sur le nouveau serveur.

Fichiers :

| Fichier | Rôle |
|---|---|
| `docker-compose.recette.yml`, `docker-compose.prod.yml` | surcharges de `docker-compose.yml` (images, durcissement, limites, réseaux) |
| `docker-compose.proxy.yml`, `infra/caddy/Caddyfile` | Caddy |
| `.env.recette.example`, `.env.prod.example`, `.env.caddy.example` | modèles des secrets (§ 4) |
| `scripts/deploy.sh` | secrets, réseaux, construction, déploiement, retour, proxy, commandes Django |
| `scripts/sauvegarde.sh`, `scripts/restauration.sh`, `infra/sauvegarde/empreinte.sql` | sauvegarde chiffrée et restauration vérifiée (§ 8) |
| `scripts/veille.sh`, `infra/systemd/*`, `infra/ops.env.example` | minuteurs systemd, veille, configuration d'exploitation |
| `infra/docker/daemon.json`, `infra/journald/alpha.conf` | journaux centralisés et rotation |
| `infra/wireguard/*.example` | VPN de la console super-administrateur (§ 9.2) |
| `docker-compose.veille.yml`, `infra/veille/Caddyfile` | Uptime Kuma, **sur une autre machine** ([`monitoring.md`](monitoring.md)) |

---

## 2. Préparation du VPS

Système conseillé : Ubuntu 24.04 LTS. Toutes les commandes sont lancées par un utilisateur
d'administration (ici `alpha`) membre du groupe `sudo`.

### 2.1 Accès et système

```bash
# En root, une seule fois
adduser alpha && usermod -aG sudo alpha
install -d -m 700 -o alpha -g alpha /home/alpha/.ssh   # puis y copier la clé publique SSH (authorized_keys)
timedatectl set-timezone Africa/Dakar
apt update && apt full-upgrade -y
apt install -y unattended-upgrades fail2ban ufw git curl ca-certificates util-linux age
```

SSH (`/etc/ssh/sshd_config.d/alpha.conf`) : `PasswordAuthentication no`, `PermitRootLogin no`,
puis `systemctl reload ssh` **après** avoir vérifié la connexion par clé dans un second terminal.

Pare-feu :

```bash
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
# Option VPN (§ 9.2) : sudo ufw allow 51820/udp
sudo ufw enable
```

Attention : Docker contourne UFW pour les ports **publiés**. C'est pourquoi seul Caddy publie des
ports (80 et 443) ; la base, Redis, Mailpit et l'API ne publient rien. Ne jamais ajouter de
`ports:` à ces services. Ajouter aussi le pare-feu du panneau Hostinger (mêmes règles) si
disponible.

Swap de 2 Go (évite les arrêts brutaux en cas de pic mémoire) :

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/90-alpha.conf && sudo sysctl --system
```

### 2.2 Docker et journaux

Docker Engine et le greffon compose depuis le dépôt officiel de Docker (pas le paquet `docker.io`
d'Ubuntu) : <https://docs.docker.com/engine/install/ubuntu/>. Compose v2.24 minimum (syntaxe
`!reset`) ; vérifier avec `docker compose version`.

```bash
cd /opt/alpha   # après le clonage (§ 2.3)
sudo install -m 644 infra/docker/daemon.json /etc/docker/daemon.json
sudo install -D -m 644 infra/journald/alpha.conf /etc/systemd/journald.conf.d/alpha.conf
sudo systemctl restart systemd-journald docker
sudo usermod -aG docker alpha   # puis se reconnecter
```

`daemon.json` envoie les journaux de tous les conteneurs dans journald (rotation : 2 Go et
30 jours au plus) et active `live-restore` (les conteneurs continuent de tourner pendant une mise
à jour de Docker). Détails : [`monitoring.md`](monitoring.md) § 4.

Membre du groupe `docker` = équivalent root : n'y mettre que les administrateurs.

### 2.3 Dépôt

```bash
sudo install -d -o alpha -g alpha /opt/alpha
git clone git@github.com:<organisation>/alpha.git /opt/alpha   # clé de déploiement GitHub en LECTURE seule
```

### 2.4 Outils de sauvegarde

```bash
sudo apt install -y age
# rclone : version officielle (celle d'Ubuntu est ancienne)
curl -fsSLO https://downloads.rclone.org/rclone-current-linux-amd64.deb && sudo apt install -y ./rclone-current-linux-amd64.deb
```

### 2.5 Versions figées

| Composant | Version | Où |
|---|---|---|
| Caddy | `caddy:2.11-alpine` (validé avec 2.11.3) | `docker-compose.proxy.yml`, `scripts/deploy.sh` (`IMAGE_CADDY`) |
| PostgreSQL | `postgres:16-alpine` | `docker-compose.yml` |
| Redis | `redis:7-alpine` | `docker-compose.yml` |
| Mailpit | `axllent/mailpit:v1.30.5` | `docker-compose.recette.yml` |
| Python / Node | 3.12 / 22 | Dockerfiles |
| Dépendances backend | `backend/requirements.lock` (empreintes SHA-256) | `pip install --require-hashes` |

Changer une version = modifier ces fichiers, passer par la recette, puis la production.

---

## 3. DNS

À créer chez le registraire **avant** le premier démarrage de Caddy (sinon l'obtention des
certificats échoue et Let's Encrypt limite les essais) :

| Nom | Type | Valeur | Remarque |
|---|---|---|---|
| `app.<domaine>` | A | IP du VPS | production (`ALPHA_DOMAINE_PROD`) |
| `recette.<domaine>` | A | IP du VPS | recette (`ALPHA_DOMAINE_RECETTE`) |
| `<domaine>` | CAA | `0 issue "letsencrypt.org"` et `0 issue "sectigo.com"` | facultatif ; limite les autorités autorisées (Sectigo = ZeroSSL, secours de Caddy) |

- Pas d'enregistrement **AAAA** tant que Docker n'est pas configuré en IPv6 : sinon les visiteurs
  IPv6 arrivent avec l'adresse interne du proxy Docker, ce qui fausse les journaux, la limitation
  de débit et la liste d'IP de la console.
- TTL de 300 s pendant la mise en place et avant tout changement de serveur (§ 11.8).
- Vérifier : `dig +short app.<domaine>` doit renvoyer l'IP du VPS.

E-mails de production (domaine d'expédition de `DEFAULT_FROM_EMAIL`) : enregistrements SPF,
DKIM et DMARC fournis par le prestataire SMTP. Sans eux, les invitations finissent en
indésirables.

---

## 4. Secrets

Un fichier par cible, à la racine de `/opt/alpha`, jamais versionné (`.gitignore`), droits 600 :

```bash
scripts/deploy.sh secrets recette   # → .env.recette : mots de passe PostgreSQL, clé Django, clés de chiffrement, poivre HMAC
scripts/deploy.sh secrets prod      # → .env.prod
scripts/deploy.sh secrets caddy     # → .env.caddy : affiche UNE fois le mot de passe des outils de recette
```

Chaque commande génère les valeurs `A_GENERER` ; complétez ensuite à la main les valeurs
`A_RENSEIGNER` (domaines, SMTP, adresses). `deploy.sh` refuse de démarrer tant qu'il en reste
une, ou si un fichier n'est pas en 600 ou contient des fins de ligne Windows.

| Variable | Fichier | Remarque |
|---|---|---|
| `ALPHA_DOMAINE_RECETTE`, `ALPHA_DOMAINE_PROD` | `.env.recette` / `.env.prod` **et** `.env.caddy` | doivent être identiques (vérifié par `deploy.sh proxy`) |
| `POSTGRES_PASSWORD`, `ALPHA_OWNER_PASSWORD`, `ALPHA_APP_PASSWORD` | `.env.<env>` | lus **une seule fois**, à la création du volume de la base |
| `DJANGO_SECRET_KEY` | `.env.<env>` | la changer déconnecte tout le monde |
| `ALPHA_CLES_CHIFFREMENT` | `.env.<env>` | **sans elle, les secrets TOTP d'une sauvegarde sont illisibles** ; rotation : ajouter la nouvelle clé EN TÊTE, garder l'ancienne |
| `ALPHA_HMAC_POIVRE` | `.env.<env>` | la changer invalide les codes de secours |
| `ALPHA_HSTS_SECONDES`, `ALPHA_HSTS_PRELOAD` | `.env.<env>` | HSTS côté Django ; `PRELOAD=false` pour le pilote (§ 12) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `DEFAULT_FROM_EMAIL` | `.env.<env>` | recette : Mailpit (ne pas changer) ; production : SMTP réel |
| `ALPHA_EMAIL_SECURITE_FYXOP` | `.env.<env>` | ancres quotidiennes et alertes de rupture de la chaîne d'audit (P7) |
| `ALPHA_GUNICORN_WORKERS`, `ALPHA_CELERY_CONCURRENCE`, `ALPHA_NIVEAU_JOURNAL` | `.env.<env>` | réglages de charge |
| `ALPHA_ACME_EMAIL` | `.env.caddy` | avis d'expiration des certificats |
| `ALPHA_IP_CONSOLE_PROD`, `ALPHA_IP_CONSOLE_RECETTE` | `.env.caddy` | § 9 |
| `ALPHA_RECETTE_OUTILS_UTILISATEUR`, `ALPHA_RECETTE_OUTILS_HASH` | `.env.caddy` | mot de passe de Mailpit et de la documentation de l'API (empreinte bcrypt seulement) |

Après génération, **copier les trois fichiers dans le gestionnaire de mots de passe de FYXOP**
(coffre partagé, accès nominatifs). En cas de perte du VPS, ce sont eux, avec la clé privée age,
qui permettent la reprise (§ 11.8).

Configuration d'exploitation (hors dépôt) :

```bash
sudo install -d -m 700 /etc/alpha
sudo install -m 600 infra/ops.env.example /etc/alpha/ops.env      # puis compléter (§ 8.1, monitoring.md)
```

---

## 5. Premier déploiement

Prérequis : § 2, § 3 (DNS résolu), § 4 (fichiers `.env.*` complets).

```bash
cd /opt/alpha
scripts/deploy.sh reseaux                      # réseaux alpha-prod-web et alpha-recette-web
git tag -l                                      # la version à déployer doit être un tag (ex. v0.1.0)
scripts/deploy.sh construire v0.1.0            # images alpha-backend:v0.1.0 et alpha-frontend:v0.1.0
scripts/deploy.sh deployer recette v0.1.0      # base, migrations, application, contrôle
scripts/deploy.sh proxy                         # valide le Caddyfile, démarre Caddy, obtient les certificats
```

Contrôles (critère de fin de D3 : « recette accessible en HTTPS ») :

```bash
curl -sI https://recette.<domaine>/ | head -n 1                       # HTTP/2 200
curl -sI https://recette.<domaine>/ | grep -i strict-transport        # HSTS présent
curl -s -o /dev/null -w '%{http_code}\n' https://recette.<domaine>/mailpit/   # 401 sans mot de passe
curl -s -o /dev/null -w '%{http_code}\n' https://recette.<domaine>/console    # 404 hors liste d'IP
curl -sI http://recette.<domaine>/ | head -n 1                        # 308 vers https
# TLS : 1.1 doit échouer, 1.2 et 1.3 réussir
for v in tls1_1 tls1_2 tls1_3; do echo -n "$v : "; openssl s_client -connect recette.<domaine>:443 -servername recette.<domaine> -$v </dev/null >/dev/null 2>&1 && echo accepté || echo refusé; done
```

Dans un navigateur : <https://recette.domaine/mailpit/> (identifiant `recette`, mot de passe
affiché par `secrets caddy`) et la documentation de l'API, <https://recette.domaine/api/v1/docs/>.

Puis, une fois la recette validée : `scripts/deploy.sh deployer prod v0.1.0`.

Créer le super-administrateur FYXOP (lien d'activation envoyé par e-mail ; en recette, il arrive
dans Mailpit) :

```bash
scripts/deploy.sh manage prod creer_super_admin --email securite@fyxop.<domaine>   # commande livrée par B10
```

Activer sauvegardes, veille et contrôle d'audit (§ 8.2) et la surveillance externe
([`monitoring.md`](monitoring.md)). **Le déploiement n'est terminé qu'après un premier test de
restauration réussi (§ 8.3).**

---

## 6. Mise à jour

```bash
cd /opt/alpha && git pull --ff-only            # fichiers compose, Caddyfile, scripts
scripts/deploy.sh construire v0.2.0
scripts/deploy.sh deployer recette v0.2.0
# … recette fonctionnelle par FYXOP …
scripts/deploy.sh deployer prod v0.2.0         # refusé si v0.2.0 n'est jamais passée en recette
scripts/deploy.sh proxy                         # seulement si le Caddyfile a changé (rechargement sans coupure)
scripts/deploy.sh nettoyer                      # garde les 5 dernières versions
```

Ce que fait `deployer` :

1. verrou (un seul déploiement à la fois), contrôle des `.env`, des images et du réseau ;
2. **sauvegarde** « avant-deploiement » si la base existe déjà (envoyée hors site) ;
3. démarrage de `db` et `redis`, puis **migrations** (`migrate`, rôle `alpha_owner`). En cas
   d'échec, l'application en service n'a pas été touchée ;
4. démarrage de l'application avec `--wait` (sondes de santé) ; si elle ne devient pas saine en
   5 minutes, **retour automatique** à la version précédente ;
5. enregistrement de la version (`.deploiements/<env>/version` et `historique`) et requête
   HTTPS de contrôle à travers Caddy.

Coupure : quelques secondes pendant le remplacement des conteneurs (Caddy affiche « ALPHA est
momentanément indisponible »). Déployer la production hors des heures de bureau et l'annoncer
aux établissements.

Règle pour les migrations (« étendre puis contracter ») : une version N+1 ne supprime ni ne
renomme une colonne encore lue par la version N. On ajoute d'abord (N+1), on retire dans une
version suivante (N+2). C'est ce qui rend le retour arrière du § 7 sûr.

---

## 7. Retour arrière

```bash
scripts/deploy.sh etat                  # versions et historique
scripts/deploy.sh retour prod           # version précédente de l'historique
scripts/deploy.sh retour prod v0.1.0    # ou une version précise (images encore présentes)
```

`retour` relance les images précédentes **sans** annuler les migrations : c'est sûr si la règle
« étendre puis contracter » a été respectée. Sinon (migration destructrice), il faut restaurer la
sauvegarde « avant-deploiement » de la version fautive :

```bash
scripts/restauration.sh prod --lister                                       # repérer …_avant-deploiement
scripts/restauration.sh prod --identite /root/cle-age.txt --sauvegarde <nom> --verifier-audit   # test dans une base à part
scripts/deploy.sh retour prod <version précédente>
scripts/restauration.sh prod --identite /root/cle-age.txt --sauvegarde <nom> --verifier-audit --remplacer
```

Les données saisies entre la sauvegarde et la restauration sont alors perdues : à décider avec
FYXOP et l'établissement, et à consigner.

---

## 8. Sauvegarde et restauration

### 8.1 Principe et mise en place

Chaque nuit, pour chaque environnement :

- `pg_dump` (format custom) et une **empreinte** de la base (structure, politiques RLS, triggers,
  droits, MD5 du contenu de chaque table) sont pris dans le **même instantané** PostgreSQL ;
- tout est chiffré **en flux** avec age vers une ou plusieurs **clés publiques** : aucun fichier
  en clair n'est écrit sur le disque, et la clé privée n'est **jamais** sur le VPS (un attaquant
  qui prend le serveur ne peut pas lire les sauvegardes) ;
- le volume des fichiers déposés (`media`) est archivé et chiffré de la même façon ;
- un manifeste en clair donne les SHA-256 des fichiers chiffrés ;
- envoi hors site par rclone (`--immutable` : aucun objet écrasé), puis `rclone check` ; copie
  supplémentaire dans `mensuel/` le 1er du mois ;
- 3 jours conservés en local (`/var/backups/alpha`, chiffrés) pour une restauration rapide ;
- signal « up » ou « down » à la surveillance (sonde push), et en cas d'échec le dossier est
  renommé `.INCOMPLETE`.

**Clés age** (sur un poste de confiance, pas sur le VPS) :

```bash
age-keygen -o alpha-sauvegarde-exploitation.key     # clé privée : coffre FYXOP + copie hors ligne (clé USB au coffre)
age-keygen -o alpha-sauvegarde-secours.key          # seconde clé, détenue par la direction (secours)
age-keygen -y alpha-sauvegarde-exploitation.key     # → ligne « age1… » à copier sur le VPS
```

Sur le VPS, `/etc/alpha/sauvegarde-destinataires.txt` (600) contient les deux lignes `age1…`
(clés publiques). Le script refuse de fonctionner si ce fichier contient une clé privée.

**Stockage hors site** : un stockage objet compatible S3 **chez un autre fournisseur que
l'hébergeur du VPS** (Backblaze B2, Scaleway Object Storage, OVHcloud, Wasabi…). Le lieu de
stockage relève aussi de la décision P8 (données personnelles, loi sénégalaise 2008-12) : les
sauvegardes sont chiffrées avant envoi, mais le choix doit être validé par FYXOP et la banque
pilote. Réglages conseillés du compartiment :

- **verrouillage d'objet** (Object Lock, mode conformité, 35 jours) ou à défaut versionnage ;
- règle de cycle de vie : préfixes `<env>/AAAA/` supprimés après 35 jours, `<env>/mensuel/` après
  12 mois (à confirmer avec FYXOP, voir questions) ;
- clé d'accès du VPS **sans droit de suppression** (écriture et lecture seulement).

```bash
sudo rclone config --config /etc/alpha/rclone.conf     # remote nommé « alpha-hors-site », type s3
sudo chmod 600 /etc/alpha/rclone.conf
# /etc/alpha/ops.env : ALPHA_SAUVEGARDE_DESTINATION=alpha-hors-site:<bucket>
sudo /opt/alpha/scripts/sauvegarde.sh recette --motif manuelle     # premier essai
```

### 8.2 Minuteurs systemd

Les unités supposent le dépôt dans `/opt/alpha`.

```bash
sudo cp /opt/alpha/infra/systemd/alpha-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alpha-sauvegarde@prod.timer alpha-sauvegarde@recette.timer   # 01:15 (+ 0 à 30 min)
sudo systemctl enable --now alpha-audit@prod.timer alpha-audit@recette.timer             # 03:15
sudo systemctl enable --now alpha-veille.timer                                           # toutes les 5 min
systemctl list-timers 'alpha-*'
```

Journaux : `journalctl -u alpha-sauvegarde@prod --since yesterday`.

Sauvegarde à la main (avant une opération risquée) :
`sudo scripts/sauvegarde.sh prod --motif manuelle`.

### 8.3 Test de restauration (mensuel, et après toute modification des scripts)

Restaure la **dernière sauvegarde hors site** dans une base **neuve**, sans toucher à la base en
service, et prouve qu'elle est fidèle :

```bash
# Apporter la clé privée le temps du test (jamais laissée sur le VPS)
sudo install -m 600 /dev/stdin /root/cle-age.txt     # coller la clé, puis Ctrl-D
sudo scripts/restauration.sh prod --identite /root/cle-age.txt --verifier-audit
sudo shred -u /root/cle-age.txt
# Supprimer ensuite la base de test indiquée par le script :
docker exec -it -u postgres $(docker ps -qf label=com.docker.compose.project=alpha-prod -f label=com.docker.compose.service=db) \
  psql -U postgres -c 'DROP DATABASE "alpha_restau_…";'
```

Étapes vérifiées par le script (codes de sortie : 0 succès, 1 erreur, 3 empreinte différente,
4 chaîne d'audit rompue) :

1. téléchargement et contrôle SHA-256 du manifeste (fichier altéré → refus) ;
2. déchiffrement (mauvaise clé → refus explicite) ;
3. `pg_restore --single-transaction --exit-on-error` dans une base neuve, propriété d'`alpha_owner`.
   Les triggers d'immutabilité du journal d'audit sont créés **après** le chargement des
   données (section post-data de pg_restore) : ils ne bloquent pas la restauration et sont actifs
   ensuite ;
4. comparaison de l'empreinte : structure, RLS activée et forcée, politiques, triggers
   (et leur état activé), fonctions, droits d'`alpha_app`, nombre de lignes et MD5 de chaque table ;
5. `verifier_chaine_audit --tous` sous le rôle `alpha_app` (donc sous RLS) ;
6. lisibilité de l'archive des fichiers déposés.

Consigner chaque test (date, sauvegarde, durée, résultat) dans le registre d'exploitation.

**Test réalisé lors de la tâche D3** (PostgreSQL 16.15 local, base `alpha_d3`, 2 établissements,
28 rôles, 6 utilisateurs, 14 événements d'audit répartis sur 3 chaînes) : sauvegarde chiffrée
vers deux clés, envoi et vérification rclone, restauration depuis le stockage dans une base
neuve, empreinte identique (228 éléments), chaînes intactes, RLS vérifiée sous `alpha_app`
(0 ligne sans contexte, isolement entre établissements, insertion croisée refusée),
UPDATE/DELETE/TRUNCATE du journal refusés même au propriétaire, chaîne prolongée normalement
après restauration (seq 7). Cas d'échec vérifiés : fichier altéré (refus), mauvaise clé (refus),
base altérée (code 4), sauvegarde en échec (`.INCOMPLETE` + signal « down »).

### 8.4 Restaurer en service

```bash
sudo scripts/restauration.sh prod --identite /root/cle-age.txt [--sauvegarde <nom>] --verifier-audit --remplacer
```

Le script restaure et vérifie d'abord dans une base neuve, demande de taper `prod`, arrête
l'application, renomme l'ancienne base en `alpha_avant_restau_<horodatage>` (conservée), bascule,
restaure les fichiers déposés et redémarre. Durée observée sur une petite base : quelques
secondes ; prévoir environ 1 min par Go de dump.

---

## 9. Accès à la console super-administrateur (P6)

Caddy n'ouvre `/console` et `/api/v1/plateforme/` qu'aux adresses de `ALPHA_IP_CONSOLE_PROD`
(et `_RECETTE`) dans `.env.caddy`, en plus de la MFA obligatoire. Hors liste : **404** (on ne
révèle pas l'existence de la console). Liste vide = console fermée depuis Internet (seul
`127.0.0.1` est autorisé). Après toute modification : `scripts/deploy.sh proxy`.

Les deux options se combinent : `ALPHA_IP_CONSOLE_PROD=203.0.113.10/32 10.66.0.0/24`.

### 9.1 Option A : adresse IP fixe de FYXOP

```
ALPHA_IP_CONSOLE_PROD=203.0.113.10/32
```

À privilégier si FYXOP dispose d'une IP fixe (fibre professionnelle). Vérifier l'adresse
réellement vue par le serveur : `curl -s https://ifconfig.me` depuis le poste.

### 9.2 Option B : VPN WireGuard sur le VPS

Pour des administrateurs sans IP fixe. Tunnel **partiel** : seul le trafic vers le VPS passe
par le VPN.

```bash
sudo apt install -y wireguard
sudo sh -c 'umask 077; wg genkey > /etc/wireguard/serveur.key; wg pubkey < /etc/wireguard/serveur.key > /etc/wireguard/serveur.pub'
sudo install -m 600 infra/wireguard/wg0.conf.example /etc/wireguard/wg0.conf   # un [Peer] par poste
sudo ufw allow 51820/udp
sudo systemctl enable --now wg-quick@wg0
# .env.caddy : ALPHA_IP_CONSOLE_PROD=10.66.0.0/24  puis  scripts/deploy.sh proxy
```

Sur le poste (`infra/wireguard/client.conf.example`) : client WireGuard officiel, puis dans le
fichier `hosts` : `10.66.0.1  app.<domaine>  recette.<domaine>`. Le navigateur joint alors Caddy
par le tunnel, avec le même certificat ; Caddy voit l'adresse `10.66.0.x`, autorisée.

Retirer un administrateur : supprimer son `[Peer]`, `sudo systemctl restart wg-quick@wg0`.

---

## 10. Monitoring

Voir [`monitoring.md`](monitoring.md) : surveillance externe (Uptime Kuma hors du VPS, alertes
e-mail), veille locale des conteneurs, du disque et de la RAM, journaux centralisés, alertes de
sauvegarde et de chaîne d'audit.

Commandes utiles :

```bash
scripts/deploy.sh etat                       # versions, conteneurs, disque
scripts/deploy.sh journaux prod backend      # suivre un service
docker stats --no-stream                     # mémoire et CPU par conteneur
systemctl list-timers 'alpha-*'; systemctl --failed
```

---

## 11. Que faire si…

### 11.1 Le site ne répond plus (alerte HTTP)

1. `scripts/deploy.sh etat` : un conteneur arrêté, « unhealthy », en boucle de redémarrage ?
2. Page « ALPHA est momentanément indisponible » : Caddy fonctionne, l'application non →
   `scripts/deploy.sh journaux prod backend` (erreur au démarrage, base injoignable…).
3. Aucune réponse : `scripts/deploy.sh journaux proxy` ; `docker ps` ; le VPS répond-il en SSH ?
   Sinon, console du panneau Hostinger (redémarrage), puis § 11.8 si le serveur est perdu.
4. Une version récente est en cause → `scripts/deploy.sh retour prod`.

### 11.2 Certificat refusé ou expiré

`scripts/deploy.sh journaux proxy | grep -i acme`. Causes : DNS qui ne pointe plus vers le VPS,
port 80 bloqué (pare-feu Hostinger), limite de Let's Encrypt (attendre ; Caddy bascule seul sur
ZeroSSL). Ne jamais supprimer le volume `alpha-proxy_caddy_data` (comptes et certificats).

### 11.3 Disque presque plein

`df -h`, `docker system df`, `journalctl --disk-usage`, `du -sh /var/backups/alpha`.
Remèdes : `scripts/deploy.sh nettoyer 3`, `sudo journalctl --vacuum-size=1G`, réduire
`ALPHA_SAUVEGARDE_RETENTION_LOCALE_JOURS`. Ne jamais supprimer un volume `*_pgdata`.

### 11.4 Mémoire insuffisante, conteneur tué (OOM)

`docker stats --no-stream` ; `journalctl -k | grep -i oom`. Remèdes : baisser
`ALPHA_GUNICORN_WORKERS` / `ALPHA_CELERY_CONCURRENCE` de la recette ; arrêter la recette pendant
un pic (`docker stop $(docker ps -q --filter label=com.docker.compose.project=alpha-recette)`,
relance par `scripts/deploy.sh deployer recette <version>`) ; puis augmenter la mémoire du VPS
ou séparer la production (recommandation P8).

### 11.5 La sauvegarde nocturne a échoué

`journalctl -u alpha-sauvegarde@prod --since -1d`. Le message de l'alerte donne l'étape :
« pg_dump » (base arrêtée ?), « envoi hors site » (identifiants rclone, quota, réseau),
« préparation » (`/etc/alpha` incomplet). Corriger, puis relancer **le jour même**
(`sudo systemctl start alpha-sauvegarde@prod`) : la perte maximale admise est de 24 h.

### 11.6 Chaîne d'audit ROMPUE

C'est un **incident de sécurité** : la preuve d'intégrité du journal est en jeu.

1. Ne rien « réparer » ni supprimer. Ne pas redémarrer la base.
2. Figer l'état : `sudo scripts/sauvegarde.sh prod --motif incident-audit`.
3. Prévenir immédiatement l'adresse sécurité FYXOP et le contrôle interne de l'établissement
   concerné (ils reçoivent aussi l'e-mail automatique et les ancres quotidiennes, P7).
4. Lire le motif : `scripts/deploy.sh manage prod verifier_chaine_audit --etablissement <code>`
   (premier `seq` invalide, nature de l'écart).
5. Restaurer dans une base à part la dernière sauvegarde où la chaîne était intacte
   (`restauration.sh … --sauvegarde <nom> --verifier-audit`) et comparer les événements pour
   identifier l'altération ; comparer aussi avec les ancres reçues par e-mail.
6. Rechercher l'accès : `journalctl` (SSH, sudo), journaux PostgreSQL, comptes ayant un accès
   `alpha_owner`/superutilisateur. Changer les mots de passe concernés (§ 11.9).
7. Consigner l'incident ; la décision de restauration revient à FYXOP et à l'établissement.

### 11.7 Le déploiement a échoué

Migrations en échec : l'application en service n'a pas été modifiée ; lire la sortie, corriger,
nouvelle version. Démarrage en échec : retour automatique effectué ; `scripts/deploy.sh journaux
prod backend` pour la cause.

### 11.8 Le VPS est perdu ou compromis (plan de reprise, objectif < 4 h)

| Étape | Durée indicative |
|---|---|
| Nouveau VPS (même offre ou autre hébergeur), § 2 | 45 min |
| Récupérer les `.env.*` et la clé age dans le coffre FYXOP, cloner le dépôt | 15 min |
| `deploy.sh reseaux`, `construire <tag en production>`, `deployer prod <tag> --sans-sauvegarde --forcer` (base vide) | 30 min |
| `restauration.sh prod --identite … --verifier-audit --remplacer` | 15 min |
| DNS vers la nouvelle IP (TTL 300 s), `deploy.sh proxy`, contrôles du § 5 | 30 min |
| Sauvegardes, veille, surveillance (§ 8.2, monitoring.md) | 30 min |

Total ≈ 3 h, avec une marge pour les imprévus. En cas de **compromission**, ne pas réutiliser
le serveur ni ses secrets : régénérer tous les secrets (`secrets … --force`) sauf
`ALPHA_CLES_CHIFFREMENT` (nécessaire pour relire les secrets TOTP restaurés ; ajouter une
nouvelle clé en tête), et forcer la reconfiguration MFA si le doute porte sur ces clés.

### 11.9 Un secret a fuité

- Mot de passe PostgreSQL : `ALTER ROLE … PASSWORD …` dans le conteneur `db` (superutilisateur),
  puis mettre à jour `.env.<env>` et `scripts/deploy.sh deployer <env> <version actuelle>`.
- `DJANGO_SECRET_KEY` : nouvelle valeur, redéploiement (toutes les sessions sont fermées).
- `ALPHA_CLES_CHIFFREMENT` : ajouter une nouvelle clé **en tête** de la liste, redéployer ; les
  secrets seront rechiffrés par la commande de rotation prévue par le backend (à confirmer).
- Mot de passe des outils de recette : `caddy hash-password` (ou
  `docker run --rm -i caddy:2.11-alpine caddy hash-password`), remplacer
  `ALPHA_RECETTE_OUTILS_HASH` (entre guillemets simples), `scripts/deploy.sh proxy`.

---

## 12. Différences entre recette et production

| Sujet | Recette (`recette.<domaine>`) | Production (`app.<domaine>`) |
|---|---|---|
| Réglages Django | `config.settings.recette` | `config.settings.prod` |
| E-mails (P11) | Mailpit, capture tout, `/mailpit/` derrière mot de passe ; aucun accès Internet | SMTP réel |
| Documentation de l'API | `/api/v1/docs/` et `/api/v1/schema/` derrière le mot de passe des outils de recette (Caddy) | coupées : non montées par Django **et** 404 dans Caddy |
| Page `/demo` (composants) | visible | masquée : 404 dans Next (`ALPHA_ENVIRONNEMENT=production`) **et** dans Caddy ; lien retiré de l'accueil |
| Console super-admin | liste d'IP `ALPHA_IP_CONSOLE_RECETTE` | liste d'IP `ALPHA_IP_CONSOLE_PROD` |
| Ressources | ≈ 2 Go, 2 processus gunicorn, 1 worker Celery | ≈ 4,5 Go, 3 processus, 2 workers |
| Journaux | journald, communs | journald, communs |

Remarque : au sprint 1, Django sert `/api/v1/schema/` sans exiger de session ; en recette, c'est
le mot de passe des outils posé par Caddy qui le protège. Exiger en plus une session ALPHA
(`SERVE_PERMISSIONS`) relève du backend.

**En-têtes posés par Caddy** (`infra/caddy/Caddyfile`), sur toutes les réponses :
`Strict-Transport-Security: max-age=31536000; includeSubDomains` (sans `preload` : l'inscription
à la liste de préchargement des navigateurs est quasi irréversible et engage tout le domaine ;
décision du titulaire du domaine), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy` et `-Resource-Policy: same-origin`,
`Permissions-Policy` restrictive, `X-Robots-Tag: noindex`, suppression de `Server`.

**CSP** :

| Réponses | Politique |
|---|---|
| API (`/api/*`) | `default-src 'none'; frame-ancestors 'none'` |
| Pages Next.js | `default-src 'self'`, `script-src 'self' 'unsafe-inline'` (scripts d'hydratation de Next 15), `frame-ancestors 'none'`, `object-src 'none'`, `form-action 'self'`. Posée seulement si Next n'en pose pas : une future CSP à nonce du frontend prendra le dessus |
| Documentation de l'API (recette) | autorise `https://cdn.jsdelivr.net` (drf-spectacular charge Swagger UI depuis ce CDN). Si le backend adopte `drf-spectacular-sidecar`, remplacer par `'self'` seul |
| Mailpit (recette) | `'self'`, websocket `wss:`, iframe de même origine |

Les jetons présents dans les URL (activation, réenrôlement, réinitialisation) sont masqués dans
le journal d'accès de Caddy ; gunicorn n'écrit pas de journal d'accès.
