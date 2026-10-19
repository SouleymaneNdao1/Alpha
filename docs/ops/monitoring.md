# Monitoring de la recette et de la production

Tâche D3. Contexte : un VPS de 8 Go partagé entre la production (≈ 4,5 Go) et la recette
(≈ 2 Go). Il reste environ 1 Go pour le système : la surveillance doit coûter presque rien
**sur le VPS**. Procédures d'intervention : [`deploiement.md`](deploiement.md) § 11.

## 1. Choix retenus

| Besoin | Solution | Coût sur le VPS | Pourquoi |
|---|---|---|---|
| Disponibilité vue de l'extérieur (HTTPS, certificats), alertes e-mail | **Uptime Kuma**, sur une **autre machine** (`docker-compose.veille.yml`) | 0 | un conteneur (~150 Mo avec son Caddy), interface simple, alertes e-mail, sondes HTTP, expiration des certificats et sondes « push ». Hors du VPS, sinon il se tait précisément quand le VPS tombe |
| État des conteneurs | sondes de santé Docker (`healthcheck`) + `scripts/veille.sh systeme` toutes les 5 min | quelques Mo pendant quelques secondes | Docker sait déjà si un service est sain ; le script en fait la synthèse et la pousse à Uptime Kuma |
| Disque, RAM, swap, OOM | `scripts/veille.sh systeme` (seuils dans `/etc/alpha/ops.env`) | idem | lecture de `df` et `/proc/meminfo`, aucun agent permanent |
| VPS injoignable | battement de cœur : chaque passage de la veille pousse « up » ; l'absence de signal déclenche l'alerte | 0 | détecte aussi une panne de systemd, de Docker ou du réseau |
| Journaux centralisés avec rotation | **journald** pour tous les conteneurs (pilote Docker `journald`) et pour les minuteurs | 0 (déjà présent) | un seul magasin, une seule politique de rotation (2 Go, 30 jours), recherche par conteneur et par période |
| Échec de la sauvegarde nocturne | sonde push par environnement : `sauvegarde.sh` envoie « up » ou « down » (étape en échec), plus `OnFailure` systemd | 0 | une sauvegarde qui ne tourne pas du tout est aussi détectée (absence de signal en 25 h) |
| Chaîne d'audit rompue | `alpha-audit@<env>.timer` → `veille.sh audit` → `verifier_chaine_audit --tous` ; code 2 → « down » | le temps de la vérification | indépendant de Celery et du SMTP : l'alerte passe même si le worker, beat ou l'envoi d'e-mails sont en panne. S'ajoute à l'e-mail envoyé par la tâche Celery de 02:00 |

Écartés : Prometheus + Grafana + Loki (1 à 2 Go de RAM, trop pour ce VPS), Netdata (200 à
400 Mo et une surface d'exposition supplémentaire), cAdvisor, Dozzle ou Portainer (ils exigent
le socket Docker, c'est-à-dire un accès root au serveur). À reconsidérer sur un VPS de production
dédié.

Disponibilité visée : 99,5 % par mois, soit au plus **3 h 39 min** d'indisponibilité par mois,
déploiements compris. Uptime Kuma en tient le compte (page de statut).

## 2. Uptime Kuma (hors du VPS)

### 2.1 Installation

Sur une petite machine distincte (1 vCPU, 1 Go, chez un autre hébergeur que le VPS, ou un
serveur de FYXOP), avec Docker :

```bash
git clone … alpha && cd alpha
cp .env.veille.example .env.veille && chmod 600 .env.veille     # domaine de l'interface, e-mail ACME
docker compose -p alpha-veille --env-file .env.veille -f docker-compose.veille.yml up -d
```

DNS : `veille.<domaine>` (A) vers **cette** machine. Ouvrir `https://veille.<domaine>`, créer le
compte administrateur, **activer la double authentification** (Paramètres → Sécurité).
Sauvegarder le volume `alpha-veille_kuma` (export JSON des sondes : Paramètres → Sauvegarde).

### 2.2 Notification e-mail

Paramètres → Notifications → « SMTP » : serveur SMTP de FYXOP (le même prestataire que la
production convient), destinataires : l'exploitant et l'adresse sécurité FYXOP. Cocher
« Activée par défaut » et « Appliquer à toutes les sondes ». Envoyer un e-mail d'essai.

### 2.3 Sondes à créer

| Nom | Type | Réglage | Intervalle |
|---|---|---|---|
| Prod — page d'accueil | HTTP(s) | `https://app.<domaine>/`, codes acceptés 200-299, **notification d'expiration du certificat** (14 j) | 60 s, 3 essais avant alerte |
| Prod — API | HTTP(s) | `https://app.<domaine>/api/v1/sante/`, codes acceptés **200-299** (voir remarque) | 60 s, 3 essais |
| Recette — page d'accueil | HTTP(s) | `https://recette.<domaine>/`, certificat (14 j) | 300 s |
| Recette — API | HTTP(s) | `https://recette.<domaine>/api/v1/sante/`, 200-299 | 300 s |
| VPS — veille | Push | URL → `ALPHA_VEILLE_PING_URL` | 300 s (alerte après ≈ 10 min sans signal) |
| Prod — sauvegarde | Push | → `ALPHA_SAUVEGARDE_PING_URL_PROD` | 90 000 s (25 h) |
| Recette — sauvegarde | Push | → `ALPHA_SAUVEGARDE_PING_URL_RECETTE` | 90 000 s |
| Prod — chaîne d'audit | Push | → `ALPHA_AUDIT_PING_URL_PROD` | 90 000 s |
| Recette — chaîne d'audit | Push | → `ALPHA_AUDIT_PING_URL_RECETTE` | 90 000 s |

Remarque sur `/api/v1/sante/` (livrée par B8) : 200 `{"statut":"ok"}` si la base et Redis
répondent, 503 `{"statut":"indisponible"}` sinon, sans autre détail ; rien n'est écrit dans le
journal d'audit. Quand le backend ne répond plus, Caddy renvoie aussi 503. Seuls les codes 200-299
comptent donc comme « sain » ; les sondes de santé Docker du backend exigent 200.

Les URL « push » contiennent un jeton : les coller dans `/etc/alpha/ops.env` (600) sur le VPS,
jamais dans le dépôt. Facultatif : une page de statut publique (sans détails) pour les
établissements.

### 2.4 Variante sans seconde machine

Si FYXOP ne dispose d'aucune autre machine, utiliser des services gratuits externes, sans rien
installer :

- **Healthchecks.io** pour les sondes push (veille, sauvegardes, audit) : les scripts
  reconnaissent ses URL (`https://hc-ping.com/<uuid>`) et envoient `/fail` en cas d'échec ;
- **UptimeRobot** (ou équivalent) pour les sondes HTTP(s) et l'expiration des certificats.

Héberger Uptime Kuma **sur le VPS lui-même** est déconseillé : à éviter sauf à garder en plus un
battement de cœur Healthchecks.io.

## 3. Veille locale (`scripts/veille.sh systeme`)

Lancée toutes les 5 minutes par `alpha-veille.timer`. Contrôles :

- projets attendus : le proxy si `.env.caddy` existe, chaque environnement déjà déployé ;
- chaque conteneur (hors `migrate` et conteneurs ponctuels) : en marche, sonde de santé non
  « unhealthy », moins de `ALPHA_VEILLE_REDEMARRAGES_MAX` redémarrages ;
- conteneurs arrêtés par manque de mémoire (OOM) ;
- disque `/`, répertoire de Docker et des sauvegardes : alerte au-delà de
  `ALPHA_VEILLE_SEUIL_DISQUE_PCT` (85 %) ;
- mémoire disponible sous `ALPHA_VEILLE_SEUIL_RAM_DISPO_MO` (500 Mo), swap au-delà de 60 % ;
- dernière sauvegarde locale réussie de plus de `ALPHA_VEILLE_SAUVEGARDE_AGE_MAX_H` (26 h).

Résultat : « up » avec un résumé (`OK /=41% ; RAM dispo 3100 Mo/7900 Mo`) ou « down » avec la
liste des problèmes, visible dans l'alerte. Code de sortie 1 en cas de problème
(`systemctl --failed`). Toute erreur imprévue du script envoie aussi « down ».

Sondes de santé Docker en place : `db` (pg_isready), `redis` (ping), `backend` (HTTP local),
`worker` (`celery inspect ping`), `frontend` (HTTP local), `mailpit` (readyz), `caddy` (API
d'administration locale). `beat` n'a pas de sonde : son état « en marche » est contrôlé, et un
beat bloqué se voit à l'absence de contrôle d'audit nocturne (sonde « chaîne d'audit »). Docker
ne redémarre pas un conteneur « unhealthy » : c'est volontaire (pas de boucle de redémarrage
masquant une panne) ; l'alerte invite à intervenir ([`deploiement.md`](deploiement.md) § 11.1).

## 4. Journaux centralisés

Tous les conteneurs (pilote `journald`, étiquette = nom du conteneur) et toutes les unités
`alpha-*` écrivent dans journald. Rotation (`infra/journald/alpha.conf`) : 2 Go au plus, fichiers
de 128 Mo, 30 jours au plus, 10 Go toujours libres sur le disque, compression.

```bash
scripts/deploy.sh journaux prod backend            # suivi d'un service (docker compose logs)
journalctl -t alpha-prod-backend-1 --since '1 hour ago'
journalctl CONTAINER_NAME=alpha-proxy-caddy-1 -o cat | grep '"status":5'    # erreurs 5xx vues par Caddy (JSON)
journalctl -u alpha-sauvegarde@prod --since yesterday
journalctl -t alpha-prod-worker-1 -p err --since today                     # erreurs seulement
journalctl --disk-usage
```

Contenu : journal d'accès de Caddy en JSON (jetons des URL masqués, cookies et en-têtes
d'authentification masqués), journaux Django avec `request_id`, Celery, PostgreSQL (requêtes de
plus d'une seconde, attentes de verrous). Gunicorn ne tient pas de journal d'accès (doublon de
Caddy, et il écrirait les jetons en clair).

Ces journaux techniques ne remplacent pas le **journal d'audit** applicatif (en base, chaîné,
conservé 10 ans).

## 5. Alertes et réactions

| Alerte | Première action |
|---|---|
| Prod / Recette — page ou API en échec | [`deploiement.md`](deploiement.md) § 11.1 |
| Certificat bientôt expiré | § 11.2 (Caddy renouvelle seul 30 jours avant : une alerte à 14 jours signifie un échec) |
| VPS — veille « down » | lire le message ; disque § 11.3, mémoire § 11.4, conteneur § 11.1 |
| VPS — veille sans signal | VPS arrêté ou injoignable : SSH, console Hostinger, puis § 11.8 |
| Sauvegarde « down » ou sans signal | § 11.5, à corriger le jour même (perte maximale 24 h) |
| Chaîne d'audit « down » | § 11.6 : **incident de sécurité** |

Essai des alertes à la mise en service, puis chaque trimestre : arrêter le frontend de la
recette quelques minutes (alerte HTTP), lancer `sudo systemctl start alpha-sauvegarde-echec@recette`
(alerte sauvegarde), vérifier la réception des e-mails.
