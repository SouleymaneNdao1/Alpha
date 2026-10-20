#!/usr/bin/env bash
# =============================================================================
# ALPHA — commandes de développement (Linux, WSL2, CI)
# Équivalent de scripts/dev.ps1 pour Windows. Lancer sans argument pour l'aide.
# =============================================================================
set -Eeuo pipefail

RACINE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

# --- Utilitaires ---------------------------------------------------------------
info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33mAttention :\033[0m %s\n' "$*" >&2; }
erreur() { printf '\033[1;31mErreur :\033[0m %s\n' "$*" >&2; exit 1; }

aide() {
	cat <<'EOF'
ALPHA — environnement de développement (docker compose)

Usage : scripts/dev.sh <commande> [arguments]

  init [--force]        Crée .env à partir de .env.example avec des secrets aléatoires
  up [service...]       Construit les images et démarre tout (ou les services cités)
  down                  Arrête et supprime les conteneurs (les données sont conservées)
  ps                    État des services
  logs [service...]     Suit les journaux (tous les services par défaut)
  migrate [args]        Applique les migrations Django (connexion alpha_owner)
  shell [service]       Shell Django dans backend ; « shell <service> » : sh dans ce conteneur
  psql [owner|app|postgres] [args]
                        Console SQL sur la base alpha (owner par défaut ; app = soumis à la RLS)
  test [args pytest]    Lance pytest dans le service « tests »
  seed [args]           Sème le jeu de démonstration dans le conteneur backend (manage.py
                        semer_demo) : comptes prêts à se connecter, QR codes et ACCES.txt dans
                        backend/demo-acces/ ; « seed --reinitialiser » régénère les identifiants
  reset [--oui]         EFFACE la base et les volumes locaux, puis redémarre tout
  help                  Affiche cette aide

Exemples :
  scripts/dev.sh up db redis mailpit     # uniquement l'infrastructure
  scripts/dev.sh logs backend worker
  scripts/dev.sh test -k rls -x
  scripts/dev.sh psql app -c "select current_user"
EOF
}

verifier_docker() {
	command -v docker >/dev/null 2>&1 ||
		erreur "commande docker introuvable. Sous WSL2 : Docker Desktop > Settings > Resources > WSL integration > activer votre distribution."
	docker compose version >/dev/null 2>&1 ||
		erreur "« docker compose » (v2) indisponible. Mettez Docker Desktop à jour."
	docker info >/dev/null 2>&1 ||
		erreur "le démon Docker ne répond pas. Démarrez Docker Desktop puis réessayez."
}

# Options TTY : rien en terminal interactif, -T en CI ou si la sortie est redirigée.
TTY=()
if ! { [ -t 0 ] && [ -t 1 ]; }; then TTY=(-T); fi

compose() { docker compose "$@"; }

valeur_env() {
	# valeur_env NOM DEFAUT : lit NOM dans .env (sans l'exporter).
	local v=""
	if [ -f .env ]; then
		v="$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d '\r')" || true
	fi
	printf '%s' "${v:-$2}"
}

hex_aleatoire() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
cle_fernet() { head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'; }

cmd_init() {
	local force="${1:-}"
	[ -f .env.example ] || erreur ".env.example introuvable dans $RACINE"
	if [ -f .env ] && [ "$force" != "--force" ]; then
		info ".env existe déjà : rien à faire (scripts/dev.sh init --force pour le régénérer)."
		return 0
	fi
	if [ -f .env ]; then
		avert ".env régénéré : si la base existe déjà, ses mots de passe ne correspondront plus (scripts/dev.sh reset)."
	fi
	local tmp ligne nom
	tmp="$(mktemp .env.XXXXXX)"
	chmod 600 "$tmp"
	while IFS= read -r ligne || [ -n "$ligne" ]; do
		ligne="${ligne%$'\r'}"
		if [[ "$ligne" =~ ^([A-Z0-9_]+)=A_GENERER$ ]]; then
			nom="${BASH_REMATCH[1]}"
			case "$nom" in
				ALPHA_CLES_CHIFFREMENT) ligne="$nom=$(cle_fernet)" ;;
				DJANGO_SECRET_KEY) ligne="$nom=$(hex_aleatoire 32)" ;;
				*) ligne="$nom=$(hex_aleatoire 24)" ;;
			esac
		elif [[ "$ligne" =~ ^ALPHA_UID= ]] && [ "$(id -u)" != "0" ]; then
			ligne="ALPHA_UID=$(id -u)"
		elif [[ "$ligne" =~ ^ALPHA_GID= ]] && [ "$(id -u)" != "0" ]; then
			ligne="ALPHA_GID=$(id -g)"
		fi
		printf '%s\n' "$ligne"
	done < .env.example > "$tmp"
	mv -f "$tmp" .env
	info ".env créé avec des secrets aléatoires (ne le commitez jamais)."
}

verifier_fins_de_ligne() {
	# Un \r dans ces fichiers casse les conteneurs (voir docs/ops/dev.md).
	local f fautifs=()
	for f in infra/postgres/init/*.sh scripts/dev.sh backend/Dockerfile frontend/Dockerfile .env docker-compose*.yml; do
		[ -f "$f" ] || continue
		if grep -q $'\r' "$f"; then fautifs+=("$f"); fi
	done
	if [ "${#fautifs[@]}" -gt 0 ]; then
		erreur "fins de ligne Windows (CRLF) détectées dans : ${fautifs[*]}. Voir docs/ops/dev.md, section « Fins de ligne »."
	fi
}

afficher_urls() {
	cat <<EOF

  Application  : http://localhost:$(valeur_env ALPHA_PORT_FRONTEND 3000)
  API (directe): http://localhost:$(valeur_env ALPHA_PORT_BACKEND 8000)/api/v1/  (docs : /api/v1/docs/)
  Mailpit      : http://localhost:$(valeur_env ALPHA_PORT_MAILPIT 8025)
  PostgreSQL   : 127.0.0.1:$(valeur_env ALPHA_PORT_DB 5432)  (base $(valeur_env ALPHA_DB_NAME alpha))
EOF
}

cmd_up() {
	if [ ! -f .env ]; then
		info "Pas de .env : création automatique."
		cmd_init
	fi
	verifier_fins_de_ligne
	info "Construction des images et démarrage…"
	if ! compose up -d --build --remove-orphans "$@"; then
		compose ps -a || true
		erreur "le démarrage a échoué. Consultez « scripts/dev.sh logs <service> » (souvent : migrate ou backend)."
	fi
	compose ps
	afficher_urls
}

cmd_reset() {
	if [ "${1:-}" != "--oui" ]; then
		avert "cette commande SUPPRIME la base de données locale et tous les volumes du projet."
		local rep
		read -r -p "Tapez « alpha » pour confirmer : " rep
		[ "$rep" = "alpha" ] || erreur "annulé."
	fi
	info "Suppression des conteneurs et des volumes…"
	compose --profile outils down -v --remove-orphans
	cmd_up
}

# --- Point d'entrée -----------------------------------------------------------
commande="${1:-help}"
[ $# -gt 0 ] && shift

case "$commande" in
	help | -h | --help | aide) aide; exit 0 ;;
	init) cmd_init "$@"; exit 0 ;;
	up | down | ps | logs | migrate | shell | psql | test | seed | reset) ;;
	*) aide; erreur "commande inconnue « $commande »." ;;
esac

verifier_docker

case "$commande" in
	up) cmd_up "$@" ;;
	down) compose --profile outils down --remove-orphans "$@" ;;
	ps) compose ps -a "$@" ;;
	logs) compose logs -f --tail=200 "$@" ;;
	migrate) compose run --rm ${TTY[@]+"${TTY[@]}"} migrate python manage.py migrate "$@" ;;
	shell)
		service="${1:-backend}"
		if [ "$service" = "backend" ]; then
			compose exec ${TTY[@]+"${TTY[@]}"} backend python manage.py shell
		else
			compose exec ${TTY[@]+"${TTY[@]}"} "$service" sh
		fi
		;;
	psql)
		role="${1:-owner}"
		[ $# -gt 0 ] && shift
		case "$role" in
			owner) role=alpha_owner ;;
			app) role=alpha_app ;;
			postgres) role=postgres ;;
			*) erreur "rôle inconnu « $role » (owner, app ou postgres)." ;;
		esac
		# Connexion par la socket locale du conteneur (sans mot de passe).
		compose exec ${TTY[@]+"${TTY[@]}"} db psql -U "$role" -d "$(valeur_env ALPHA_DB_NAME alpha)" "$@"
		;;
	test) compose --profile outils run --rm ${TTY[@]+"${TTY[@]}"} tests pytest "$@" ;;
	seed)
		# Dans le conteneur backend (connexion alpha_app, RLS active) ; le dossier de sortie
		# demo-acces/ est dans backend/, monté dans /app : accessible depuis le poste.
		compose exec ${TTY[@]+"${TTY[@]}"} backend python manage.py semer_demo "$@"
		;;
	reset) cmd_reset "$@" ;;
	*)
		aide
		erreur "commande inconnue « $commande »."
		;;
esac
