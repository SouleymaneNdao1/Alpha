<#
.SYNOPSIS
    ALPHA - commandes de développement pour Windows (PowerShell 5.1 ou 7).

.DESCRIPTION
    Encapsule `docker compose` (architecture § 1.3). Lancer sans argument pour l'aide.

    Si le dépôt est dans le système de fichiers WSL2 (\\wsl$\<distro>\... ou
    \\wsl.localhost\<distro>\..., configuration recommandée), les commandes
    docker sont exécutées DANS la distribution via wsl.exe : les montages de
    code et la surveillance des fichiers fonctionnent alors nativement.
    Sinon (dépôt sur C:\...), docker compose est appelé directement.

.EXAMPLE
    .\scripts\dev.ps1 up
.EXAMPLE
    .\scripts\dev.ps1 logs backend worker
.EXAMPLE
    .\scripts\dev.ps1 test -k rls -x

.NOTES
    Fichier enregistré en UTF-8 AVEC BOM : indispensable pour que Windows
    PowerShell 5.1 affiche correctement les accents.
    Pas de bloc param() : les arguments sont lus dans $args pour que les options
    destinées à pytest ou psql (-k, -x, -c ...) ne soient pas interprétées par
    PowerShell.
#>

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Racine = (Split-Path -Parent $PSScriptRoot) -replace '^Microsoft\.PowerShell\.Core\\FileSystem::', ''
$ModeWsl = $false
$Distro = $null
$CheminLinux = $null
if ($Racine -match '^\\\\wsl(\$|\.localhost)\\([^\\]+)\\(.*)$') {
    $ModeWsl = $true
    $Distro = $Matches[2]
    $CheminLinux = '/' + ($Matches[3] -replace '\\', '/')
}

# --- Affichage -----------------------------------------------------------------
function Write-Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Avert([string]$Message) { Write-Host "Attention : $Message" -ForegroundColor Yellow }
function Stop-Erreur([string]$Message) {
    Write-Host "Erreur : $Message" -ForegroundColor Red
    exit 1
}

function Show-Aide {
    @'
ALPHA - environnement de développement (docker compose)

Usage : .\scripts\dev.ps1 <commande> [arguments]

  init [--force]        Crée .env à partir de .env.example avec des secrets aléatoires
  up [service...]       Construit les images et démarre tout (ou les services cités)
  down                  Arrête et supprime les conteneurs (les données sont conservées)
  ps                    État des services
  logs [service...]     Suit les journaux (tous les services par défaut ; Ctrl+C pour quitter)
  migrate [args]        Applique les migrations Django (connexion alpha_owner)
  shell [service]       Shell Django dans backend ; « shell <service> » : sh dans ce conteneur
  psql [owner|app|postgres] [args]
                        Console SQL sur la base alpha (owner par défaut ; app = soumis à la RLS)
  test [args pytest]    Lance pytest dans le service « tests »
  seed [args]           Sème le jeu de démonstration dans le conteneur backend (manage.py
                        semer_demo) : comptes prêts à se connecter, QR codes et ACCES.txt dans
                        backend\demo-acces\ ; « seed --reinitialiser » régénère les identifiants
  reset [--oui]         EFFACE la base et les volumes locaux, puis redémarre tout
  help                  Affiche cette aide

Exemples :
  .\scripts\dev.ps1 up db redis mailpit     # uniquement l'infrastructure
  .\scripts\dev.ps1 logs backend worker
  .\scripts\dev.ps1 test -k rls -x
  .\scripts\dev.ps1 psql app -c "select current_user"
'@ | Write-Host
    if ($ModeWsl) {
        Write-Host "Mode : dépôt dans WSL2 (distribution « $Distro », chemin $CheminLinux)." -ForegroundColor DarkGray
    } else {
        Write-Host "Mode : dépôt sur le disque Windows ($Racine)." -ForegroundColor DarkGray
    }
}

# --- Exécution de docker -------------------------------------------------------
# Lance une commande (docker, id, chmod...) soit sous Windows, soit dans la
# distribution WSL2 qui contient le dépôt. Le code de retour est dans $LASTEXITCODE.
function Invoke-Outil {
    param([Parameter(Mandatory = $true)][string]$Programme, [string[]]$Arguments = @())
    if ($ModeWsl) {
        & wsl.exe -d $Distro --cd $CheminLinux --exec $Programme @Arguments
    } else {
        Push-Location -LiteralPath $Racine
        try { & $Programme @Arguments } finally { Pop-Location }
    }
}

function Invoke-Compose {
    param([string[]]$Arguments = @())
    Invoke-Outil -Programme 'docker' -Arguments (@('compose') + $Arguments)
}

# Variante qui arrête le script si la commande échoue.
function Invoke-ComposeOuEchec {
    param([string[]]$Arguments = @(), [string]$MessageEchec = 'la commande docker compose a échoué.')
    Invoke-Compose -Arguments $Arguments
    if ($LASTEXITCODE -ne 0) { Stop-Erreur "$MessageEchec (code $LASTEXITCODE)" }
}

function Test-Docker {
    # Les erreurs des commandes natives ne doivent pas interrompre le test.
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($ModeWsl) {
            if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
                Stop-Erreur 'wsl.exe introuvable : installez WSL2 (wsl --install).'
            }
            & wsl.exe -d $Distro --exec sh -c 'command -v docker' *> $null
            if ($LASTEXITCODE -ne 0) {
                Stop-Erreur "docker introuvable dans la distribution « $Distro ». Docker Desktop > Settings > Resources > WSL integration : activez « $Distro »."
            }
        } elseif (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Stop-Erreur 'docker introuvable. Installez Docker Desktop (moteur WSL2) puis rouvrez PowerShell.'
        }
        Invoke-Outil -Programme 'docker' -Arguments @('compose', 'version') *> $null
        if ($LASTEXITCODE -ne 0) { Stop-Erreur '« docker compose » (v2) indisponible : mettez Docker Desktop à jour.' }
        Invoke-Outil -Programme 'docker' -Arguments @('info') *> $null
        if ($LASTEXITCODE -ne 0) { Stop-Erreur 'le moteur Docker ne répond pas. Démarrez Docker Desktop puis réessayez.' }
    } finally {
        $ErrorActionPreference = $ancien
    }
}

# --- Fichier .env --------------------------------------------------------------
function Get-CheminRacine([string]$Relatif) { return (Join-Path $Racine $Relatif) }

function Get-ValeurEnv([string]$Nom, [string]$Defaut) {
    $fichier = Get-CheminRacine '.env'
    if (-not (Test-Path -LiteralPath $fichier)) { return $Defaut }
    $valeur = $null
    foreach ($ligne in [System.IO.File]::ReadAllLines($fichier)) {
        if ($ligne.StartsWith("$Nom=")) { $valeur = $ligne.Substring($Nom.Length + 1).Trim() }
    }
    if ([string]::IsNullOrEmpty($valeur)) { return $Defaut }
    return $valeur
}

function New-OctetsAleatoires([int]$Nombre) {
    $octets = New-Object byte[] $Nombre
    $generateur = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generateur.GetBytes($octets) } finally { $generateur.Dispose() }
    return , $octets
}

function New-SecretHex([int]$Nombre) {
    $octets = New-OctetsAleatoires $Nombre
    $sb = New-Object System.Text.StringBuilder
    foreach ($o in $octets) { [void]$sb.Append($o.ToString('x2')) }
    return $sb.ToString()
}

function New-CleFernet {
    # 32 octets en base64 « URL-safe » (format attendu par cryptography.fernet).
    $octets = New-OctetsAleatoires 32
    return [Convert]::ToBase64String($octets).Replace('+', '-').Replace('/', '_')
}

function Invoke-Init([string[]]$Options = @()) {
    $exemple = Get-CheminRacine '.env.example'
    $cible = Get-CheminRacine '.env'
    if (-not (Test-Path -LiteralPath $exemple)) { Stop-Erreur ".env.example introuvable dans $Racine" }
    $force = $Options -contains '--force' -or $Options -contains '-force'
    if ((Test-Path -LiteralPath $cible) -and -not $force) {
        Write-Info '.env existe déjà : rien à faire (.\scripts\dev.ps1 init --force pour le régénérer).'
        return
    }
    if (Test-Path -LiteralPath $cible) {
        Write-Avert '.env régénéré : si la base existe déjà, ses mots de passe ne correspondront plus (.\scripts\dev.ps1 reset).'
    }

    # UID/GID de l'utilisateur WSL (les fichiers créés par les conteneurs lui appartiendront).
    $uid = $null; $gid = $null
    if ($ModeWsl) {
        $uid = (& wsl.exe -d $Distro --exec id -u | Out-String).Trim()
        $gid = (& wsl.exe -d $Distro --exec id -g | Out-String).Trim()
        if ($uid -notmatch '^[1-9][0-9]*$') { $uid = $null; $gid = $null }
    }

    $lignes = New-Object System.Collections.Generic.List[string]
    foreach ($ligne in [System.IO.File]::ReadAllLines($exemple)) {
        $ligne = $ligne.TrimEnd("`r")
        if ($ligne -match '^([A-Z0-9_]+)=A_GENERER$') {
            $nom = $Matches[1]
            switch ($nom) {
                'ALPHA_CLES_CHIFFREMENT' { $ligne = "$nom=$(New-CleFernet)" }
                'DJANGO_SECRET_KEY' { $ligne = "$nom=$(New-SecretHex 32)" }
                default { $ligne = "$nom=$(New-SecretHex 24)" }
            }
        } elseif ($uid -and $ligne -match '^ALPHA_UID=') {
            $ligne = "ALPHA_UID=$uid"
        } elseif ($gid -and $ligne -match '^ALPHA_GID=') {
            $ligne = "ALPHA_GID=$gid"
        }
        $lignes.Add($ligne)
    }

    # UTF-8 SANS BOM et fins de ligne LF : sinon docker compose lit mal le fichier.
    $contenu = ($lignes -join "`n") + "`n"
    [System.IO.File]::WriteAllText($cible, $contenu, (New-Object System.Text.UTF8Encoding($false)))
    if ($ModeWsl) {
        & wsl.exe -d $Distro --cd $CheminLinux --exec chmod 600 .env
    }
    Write-Info '.env créé avec des secrets aléatoires (ne le commitez jamais).'
}

# --- Contrôles -----------------------------------------------------------------
function Test-FinsDeLigne {
    $candidats = @(Get-ChildItem -LiteralPath (Get-CheminRacine 'infra\postgres\init') -Filter '*.sh' -File -Force -ErrorAction SilentlyContinue)
    foreach ($relatif in @('scripts\dev.sh', 'backend\Dockerfile', 'frontend\Dockerfile', '.env', 'docker-compose.yml', 'docker-compose.override.yml')) {
        $chemin = Get-CheminRacine $relatif
        if (Test-Path -LiteralPath $chemin) { $candidats += Get-Item -LiteralPath $chemin -Force }
    }
    $fautifs = @()
    foreach ($f in $candidats) {
        if ([System.IO.File]::ReadAllText($f.FullName).Contains("`r")) { $fautifs += $f.Name }
    }
    if ($fautifs.Count -gt 0) {
        Stop-Erreur ("fins de ligne Windows (CRLF) détectées dans : " + ($fautifs -join ', ') + ". Voir docs/ops/dev.md, section « Fins de ligne ».")
    }
}

function Show-Urls {
    Write-Host ''
    Write-Host "  Application   : http://localhost:$(Get-ValeurEnv 'ALPHA_PORT_FRONTEND' '3000')"
    Write-Host "  API (directe) : http://localhost:$(Get-ValeurEnv 'ALPHA_PORT_BACKEND' '8000')/api/v1/  (docs : /api/v1/docs/)"
    Write-Host "  Mailpit       : http://localhost:$(Get-ValeurEnv 'ALPHA_PORT_MAILPIT' '8025')"
    Write-Host "  PostgreSQL    : 127.0.0.1:$(Get-ValeurEnv 'ALPHA_PORT_DB' '5432')  (base $(Get-ValeurEnv 'ALPHA_DB_NAME' 'alpha'))"
}

# --- Commandes -----------------------------------------------------------------
function Invoke-Up([string[]]$Services = @()) {
    if (-not (Test-Path -LiteralPath (Get-CheminRacine '.env'))) {
        Write-Info 'Pas de .env : création automatique.'
        Invoke-Init
    }
    Test-FinsDeLigne
    Write-Info 'Construction des images et démarrage...'
    Invoke-Compose -Arguments (@('up', '-d', '--build', '--remove-orphans') + $Services)
    if ($LASTEXITCODE -ne 0) {
        Invoke-Compose -Arguments @('ps', '-a')
        Stop-Erreur 'le démarrage a échoué. Consultez « .\scripts\dev.ps1 logs <service> » (souvent : migrate ou backend).'
    }
    Invoke-Compose -Arguments @('ps')
    Show-Urls
}

function Invoke-Reset([string[]]$Options = @()) {
    if (-not ($Options -contains '--oui' -or $Options -contains '-oui')) {
        Write-Avert 'cette commande SUPPRIME la base de données locale et tous les volumes du projet.'
        $reponse = Read-Host 'Tapez « alpha » pour confirmer'
        if ($reponse -ne 'alpha') { Stop-Erreur 'annulé.' }
    }
    Write-Info 'Suppression des conteneurs et des volumes...'
    Invoke-ComposeOuEchec -Arguments @('--profile', 'outils', 'down', '-v', '--remove-orphans')
    Invoke-Up
}

# --- Point d'entrée ------------------------------------------------------------
$Commande = 'help'
$Reste = @()
if ($args.Count -ge 1) { $Commande = [string]$args[0] }
if ($args.Count -ge 2) { $Reste = @($args[1..($args.Count - 1)] | ForEach-Object { [string]$_ }) }

switch ($Commande) {
    { $_ -in @('help', '-h', '--help', '-help', 'aide', '/?') } { Show-Aide; exit 0 }
    'init' { Invoke-Init $Reste; exit 0 }
    { $_ -in @('up', 'down', 'ps', 'logs', 'migrate', 'shell', 'psql', 'test', 'seed', 'reset') } { break }
    default { Show-Aide; Stop-Erreur "commande inconnue « $Commande »." }
}

Test-Docker

switch ($Commande) {
    'up' { Invoke-Up $Reste }
    'down' { Invoke-Compose -Arguments (@('--profile', 'outils', 'down', '--remove-orphans') + $Reste) }
    'ps' { Invoke-Compose -Arguments (@('ps', '-a') + $Reste) }
    'logs' { Invoke-Compose -Arguments (@('logs', '-f', '--tail=200') + $Reste) }
    'migrate' { Invoke-Compose -Arguments (@('run', '--rm', 'migrate', 'python', 'manage.py', 'migrate') + $Reste) }
    'shell' {
        $service = 'backend'
        if ($Reste.Count -ge 1) { $service = $Reste[0] }
        if ($service -eq 'backend') {
            Invoke-Compose -Arguments @('exec', 'backend', 'python', 'manage.py', 'shell')
        } else {
            Invoke-Compose -Arguments @('exec', $service, 'sh')
        }
    }
    'psql' {
        $role = 'owner'
        $options = @()
        if ($Reste.Count -ge 1) { $role = $Reste[0] }
        if ($Reste.Count -ge 2) { $options = @($Reste[1..($Reste.Count - 1)]) }
        switch ($role) {
            'owner' { $roleSql = 'alpha_owner' }
            'app' { $roleSql = 'alpha_app' }
            'postgres' { $roleSql = 'postgres' }
            default { Stop-Erreur "rôle inconnu « $role » (owner, app ou postgres)." }
        }
        # Connexion par la socket locale du conteneur (sans mot de passe).
        $base = Get-ValeurEnv 'ALPHA_DB_NAME' 'alpha'
        Invoke-Compose -Arguments (@('exec', 'db', 'psql', '-U', $roleSql, '-d', $base) + $options)
    }
    'test' { Invoke-Compose -Arguments (@('--profile', 'outils', 'run', '--rm', 'tests', 'pytest') + $Reste) }
    'seed' {
        # Dans le conteneur backend (connexion alpha_app, RLS active) ; le dossier de sortie
        # demo-acces\ est dans backend\, monté dans /app : accessible depuis le poste.
        Invoke-Compose -Arguments (@('exec', 'backend', 'python', 'manage.py', 'semer_demo') + $Reste)
    }
    'reset' { Invoke-Reset $Reste }
}

exit $LASTEXITCODE
