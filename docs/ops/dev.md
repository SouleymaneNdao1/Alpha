# Dépannage du poste de développement (Windows / WSL2)

Configuration de référence : dépôt cloné **dans Ubuntu (WSL2)**, Docker Desktop en moteur WSL2,
commandes lancées par `scripts\dev.ps1` (PowerShell) ou `scripts/dev.sh` (terminal Ubuntu).
Voir le [README](../../README.md) pour l'installation.

Réflexes de diagnostic :

```powershell
.\scripts\dev.ps1 ps              # quel service est arrêté, « unhealthy » ou « exited (1) » ?
.\scripts\dev.ps1 logs migrate    # puis le service en cause : db, backend, frontend…
```

---

## 1. Fins de ligne (CRLF)

**Symptômes**
- `db` s'arrête au premier démarrage avec `/usr/bin/env: 'bash\r': No such file or directory`
  ou `$'\r': command not found` dans `.\scripts\dev.ps1 logs db` ;
- `scripts/dev.sh` échoue dans Ubuntu avec les mêmes messages ;
- `dev.ps1 up` / `dev.sh up` s'arrêtent avec « fins de ligne Windows (CRLF) détectées dans … » ;
- authentification PostgreSQL refusée alors que les mots de passe semblent bons (un `\r` invisible
  termine la valeur dans `.env`).

**Cause** : Git pour Windows avec `core.autocrlf=true`, ou un éditeur qui enregistre en CRLF. Le
dépôt impose LF par `.gitattributes` (`* text=auto eol=lf`) et `.editorconfig`, mais un clone fait
avant ces réglages ou un fichier réenregistré peut contenir des CRLF.

**Correction**

```bash
# Dans Ubuntu, à la racine du dépôt
git config --global core.autocrlf input
git config core.autocrlf input
git add --renormalize . && git status          # les fichiers corrigés apparaissent modifiés
sed -i 's/\r$//' .env                           # .env n'est pas suivi par Git
```

Pour un seul fichier : `sed -i 's/\r$//' infra/postgres/init/01-roles.sh` (ou `dos2unix`).
Dans VS Code : en bas à droite, cliquer sur « CRLF » et choisir « LF ».

**Important** : si `01-roles.sh` a échoué, le volume de la base est à moitié initialisé et le script
ne sera **pas** rejoué automatiquement. Après correction : `.\scripts\dev.ps1 reset`.

`scripts\dev.ps1` peut rester en LF ; il doit en revanche être enregistré en **UTF-8 avec BOM**
(sinon Windows PowerShell 5.1 affiche « Ã© » à la place des accents, voire refuse de l'analyser).

## 2. Ports déjà pris

**Symptômes** : `up` échoue avec
- `Bind for 127.0.0.1:5432 failed: port is already allocated`, ou
- `Ports are not available: exposing port TCP 127.0.0.1:3000 … An attempt was made to access a
  socket in a way forbidden by its access permissions`.

Ports utilisés : 3000 (frontend), 8000 (API), 8025 (Mailpit), 5432 (PostgreSQL).

**Trouver le coupable** (PowerShell) :

```powershell
Get-NetTCPConnection -LocalPort 5432 -State Listen | ForEach-Object { Get-Process -Id $_.OwningProcess }
netsh interface ipv4 show excludedportrange protocol=tcp   # plages réservées par Hyper-V / WinNAT
```

**Solutions**
- un PostgreSQL installé sous Windows occupe 5432 : `Stop-Service postgresql*` (administrateur) ou
  changer de port ;
- un autre projet Docker occupe le port : l'arrêter (`docker ps` pour le trouver) ;
- changer le port côté hôte dans `.env` (`ALPHA_PORT_DB=55432`, `ALPHA_PORT_FRONTEND=3001`, …) puis
  `.\scripts\dev.ps1 down` et `.\scripts\dev.ps1 up` ; les conteneurs, eux, gardent leurs ports ;
- port dans une plage réservée par Hyper-V (message « forbidden by its access permissions ») :
  choisir un port hors des plages listées, ou, en administrateur, `net stop winnat` puis
  `net start winnat`.

## 3. Mémoire WSL2

**Symptômes** : le processus `VmmemWSL` (ou `Vmmem`) occupe plusieurs Go, le PC ralentit, ou un
conteneur est tué (`exited (137)`, « OOMKilled » dans `docker inspect`), souvent `frontend` pendant
`next dev` ou la construction des images.

Ordre de grandeur de la pile de développement : 2,5 à 3,5 Go (dont ~1 Go pour `next dev`).

**Réglage** : créer `%UserProfile%\.wslconfig` (par exemple `C:\Users\pape\.wslconfig`) :

```ini
[wsl2]
# 6 Go sur un poste de 16 Go ; 4GB minimum pour ALPHA
memory=6GB
processors=4
swap=4GB

[experimental]
# Rend progressivement à Windows la mémoire inutilisée
autoMemoryReclaim=gradual
```

(Les commentaires doivent être sur leur propre ligne : WSL ne les accepte pas en fin de valeur.)

Puis appliquer : fermer Docker Desktop, `wsl --shutdown` dans PowerShell, relancer Docker Desktop.
En moteur WSL2, ce fichier remplace les réglages de mémoire de Docker Desktop.

**Disque** : les images et caches s'accumulent dans le disque virtuel WSL.

```powershell
docker system df                 # place utilisée
docker builder prune             # cache de construction
docker image prune               # images orphelines
```

## 4. Autres problèmes fréquents

| Symptôme | Cause et solution |
|---|---|
| « …dev.ps1 cannot be loaded because running scripts is disabled » ou « is not digitally signed » | Stratégie d'exécution. Une fois : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Si le chemin `\\wsl.localhost\…` est encore considéré comme distant : `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 up`. |
| « docker introuvable dans la distribution Ubuntu » | Docker Desktop > *Settings > Resources > WSL integration* : activer la distribution, *Apply & restart*. |
| « le moteur Docker ne répond pas » | Docker Desktop n'est pas démarré, ou démarre encore (attendre l'icône verte). |
| `migrate` en échec avec `can't open file '/app/manage.py'` | Normal tant que la tâche B1 n'est pas livrée : `.\scripts\dev.ps1 up db redis mailpit`. |
| `password authentication failed for user "alpha_app"` | `.env` a été régénéré ou modifié après la création de la base. Les mots de passe ne sont lus qu'au premier démarrage : `.\scripts\dev.ps1 reset`. |
| `01-roles.sh : mot de passe trop court ou encore à la valeur d'exemple` | `.env` copié à la main depuis `.env.example` : lancer `.\scripts\dev.ps1 init --force`, puis `reset`. |
| Fichiers créés par les conteneurs (migrations générées…) non modifiables dans Ubuntu | UID différent de 1000 : mettre `ALPHA_UID` / `ALPHA_GID` (commande `id` dans Ubuntu) dans `.env`, puis `up` (reconstruit l'image). |
| Les modifications du code ne rechargent pas Next.js | Dépôt sur `C:\` : `WATCHPACK_POLLING=true` dans `.env` (et envisager de déplacer le dépôt dans WSL2). |
| Après un changement de `package.json`, un module reste introuvable | `node_modules` est un volume anonyme : `.\scripts\dev.ps1 down` puis `.\scripts\dev.ps1 up` (le volume est recréé depuis la nouvelle image). |
| Codes TOTP refusés en local après une mise en veille du PC | Horloge de WSL2 décalée. Vérifier avec `date` dans Ubuntu ; corriger avec `wsl --shutdown` (ou `sudo hwclock -s` dans Ubuntu). |
| Accents illisibles dans les messages de `dev.ps1` | Fichier réenregistré sans BOM : le rouvrir et l'enregistrer en « UTF-8 with BOM ». |
