#!/usr/bin/env bash
# =============================================================================
# ALPHA — déploiement de la recette et de la production sur le VPS (tâche D3)
#
# Usage : scripts/deploy.sh <commande> [arguments]
#
#   secrets <recette|prod|caddy> [--force]
#                         crée .env.<cible> (droits 600) depuis son modèle et
#                         génère chaque valeur A_GENERER ; pour caddy, génère et
#                         affiche UNE fois le mot de passe des outils de recette
#   reseaux               crée les réseaux partagés avec Caddy (alpha-prod-web,
#                         alpha-recette-web), internes, sans accès Internet
#   construire <ref git>  construit alpha-backend:<version> et alpha-frontend:<version>
#                         depuis un tag (recommandé, ex. v0.1.0) ou un commit ;
#                         affiche la version obtenue
#   deployer <recette|prod> <version> [--sans-sauvegarde] [--forcer]
#                         sauvegarde, migrations, démarrage, contrôle ; retour
#                         automatique à la version précédente si le démarrage échoue.
#                         En prod, la version doit être passée par la recette
#                         (sinon --forcer)
#   retour <recette|prod> [version]
#                         revient à la version précédente (ou indiquée), SANS
#                         migration (voir docs/ops/deploiement.md § 7)
#   proxy                 valide le Caddyfile puis démarre/recharge Caddy sans coupure
#   manage <recette|prod> <args…>
#                         commande Django d'exploitation (rôle alpha_owner), ex. :
#                         manage prod creer_super_admin --email …
#   etat                  versions déployées, historique, état des conteneurs
#   journaux <recette|prod|proxy> [service…]
#                         suit les journaux
#   nettoyer [N]          supprime les images de plus de N versions (défaut 5),
#                         jamais celles en service
#
# Principe : les fichiers compose et le Caddyfile viennent de CETTE copie du
# dépôt (branche main, mise à jour par git pull) ; le code applicatif vient des
# IMAGES, étiquetées par version. Revenir en arrière = relancer l'image
# précédente, toujours présente sur le VPS.
#
# Aucune option ne contourne les contrôles de sécurité (.env en 600, aucune
# valeur d'exemple, version déjà validée en recette avant la production).
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
# shellcheck source=scripts/ops-commun.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/ops-commun.sh"
cd "$ALPHA_RACINE"

IMAGE_CADDY="caddy:2.11-alpine"

aide() {
	sed -n '2,/^# =====/p' "$SCRIPT" | sed -e 's/^# \{0,1\}//' -e '/^=====/d'
}

verifier_docker() {
	command -v docker >/dev/null 2>&1 || erreur "docker introuvable (docs/ops/deploiement.md § 2)."
	docker compose version >/dev/null 2>&1 || erreur "docker compose v2 introuvable."
	docker info >/dev/null 2>&1 || erreur "le démon Docker ne répond pas (droits ? sudo ?)."
}

# Un seul déploiement à la fois sur le VPS.
verrouiller() {
	mkdir -p "$ALPHA_ETAT"
	chmod 700 "$ALPHA_ETAT"
	exec 8>"$ALPHA_ETAT/.verrou"
	flock -n 8 || erreur "un autre déploiement est en cours."
}

image_existe() { docker image inspect "$1" >/dev/null 2>&1; }

# Services d'un environnement, hors migrate (lancé à part).
services_appli() {
	compose_env "$1" config --services | grep -vx migrate | tr '\n' ' '
}

# --- secrets -----------------------------------------------------------------------
hex_aleatoire() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
cle_fernet() { head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'; }

hacher_mot_de_passe() {
	# Empreinte bcrypt pour basic_auth de Caddy ; le mot de passe passe par
	# l'entrée standard (jamais dans la ligne de commande).
	if command -v caddy >/dev/null 2>&1; then
		printf '%s\n' "$1" | caddy hash-password
	else
		printf '%s\n' "$1" | docker run --rm -i "$IMAGE_CADDY" caddy hash-password
	fi
}

cmd_secrets() {
	local cible="${1:-}" force="${2:-}" modele f tmp ligne nom mdp hash
	case "$cible" in recette | prod | caddy) ;; *) erreur "usage : secrets <recette|prod|caddy> [--force]" ;; esac
	modele="$ALPHA_RACINE/.env.$cible.example"
	f="$(fichier_env "$cible")"
	[ -f "$modele" ] || erreur "$modele introuvable."
	if [ -f "$f" ] && [ "$force" != "--force" ]; then
		info "$f existe déjà : rien à faire (--force pour le régénérer)."
		return 0
	fi
	if [ -f "$f" ]; then
		avert "$f régénéré : si la base de $cible existe déjà, ses mots de passe ne correspondront plus."
	fi
	tmp="$(mktemp "$ALPHA_RACINE/.env.$cible.XXXXXX")"
	chmod 600 "$tmp"
	mdp=""
	while IFS= read -r ligne || [ -n "$ligne" ]; do
		ligne="${ligne%$'\r'}"
		if [[ "$ligne" =~ ^([A-Z0-9_]+)=A_GENERER$ ]]; then
			nom="${BASH_REMATCH[1]}"
			case "$nom" in
				ALPHA_CLES_CHIFFREMENT) ligne="$nom=$(cle_fernet)" ;;
				DJANGO_SECRET_KEY) ligne="$nom=$(hex_aleatoire 32)" ;;
				*) ligne="$nom=$(hex_aleatoire 24)" ;;
			esac
		elif [[ "$ligne" =~ ^ALPHA_RECETTE_OUTILS_HASH=\'A_GENERER\'$ ]]; then
			mdp="$(head -c 18 /dev/urandom | base64 | tr '+/' '-_')"
			hash="$(hacher_mot_de_passe "$mdp")"
			[[ "$hash" == \$2* ]] || erreur "échec du calcul de l'empreinte bcrypt."
			ligne="ALPHA_RECETTE_OUTILS_HASH='$hash'"
		fi
		printf '%s\n' "$ligne"
	done <"$modele" >"$tmp"
	mv -f "$tmp" "$f"
	ok "$f créé (droits 600). Copiez ses secrets dans le gestionnaire de mots de passe de FYXOP."
	if [ -n "$mdp" ]; then
		printf '\n  Mot de passe des outils de recette (Mailpit, documentation de l'"'"'API)\n  utilisateur : %s\n  mot de passe : %s\n  (affiché une seule fois : notez-le maintenant)\n\n' \
			"$(valeur_env "$f" ALPHA_RECETTE_OUTILS_UTILISATEUR)" "$mdp" >&2
	fi
	if grep -qE '^[^#]*A_RENSEIGNER' "$f"; then
		avert "complétez à la main les valeurs A_RENSEIGNER de $f :"
		grep -nE '^[^#]*A_RENSEIGNER' "$f" | sed 's/^/    /' >&2
	fi
}

# --- reseaux -------------------------------------------------------------------------
cmd_reseaux() {
	verifier_docker
	local r
	for r in alpha-prod-web alpha-recette-web; do
		if docker network inspect "$r" >/dev/null 2>&1; then
			info "réseau $r : déjà présent."
		else
			# --internal : ni Caddy ni les conteneurs ne sortent par ce réseau.
			docker network create --driver bridge --internal "$r" >/dev/null
			ok "réseau $r créé."
		fi
	done
}

# --- construire ------------------------------------------------------------------------
cmd_construire() {
	local ref="${1:-}" sha version
	[ -n "$ref" ] || erreur "usage : construire <tag ou commit>"
	verifier_docker
	command -v git >/dev/null 2>&1 || erreur "git introuvable."
	if git remote get-url origin >/dev/null 2>&1; then
		info "Récupération des tags et branches (git fetch)"
		git fetch --tags --quiet origin || avert "git fetch a échoué : construction depuis l'état local."
	fi
	sha="$(git rev-parse --verify --quiet "${ref}^{commit}")" || erreur "référence git inconnue : $ref"
	version="$(git describe --tags --exact-match "$sha" 2>/dev/null || printf 'g%s' "${sha:0:12}")"
	[[ "$version" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || erreur "version invalide pour une étiquette d'image : $version"
	info "Construction de la version $version (commit ${sha:0:12})"
	# Contexte de construction = contenu EXACT du commit (git archive) : les
	# fichiers modifiés ou non suivis de cette copie de travail n'entrent pas
	# dans l'image.
	git archive --format=tar "$sha:backend" |
		docker build --target prod -t "alpha-backend:$version" \
			--label "org.opencontainers.image.revision=$sha" \
			--label "org.opencontainers.image.version=$version" -
	git archive --format=tar "$sha:frontend" |
		docker build --target prod -t "alpha-frontend:$version" \
			--label "org.opencontainers.image.revision=$sha" \
			--label "org.opencontainers.image.version=$version" -
	ok "images alpha-backend:$version et alpha-frontend:$version prêtes."
	printf '%s\n' "$version"
}

# --- deployer ------------------------------------------------------------------------
enregistrer_version() {
	local env="$1" version="$2" action="$3"
	mkdir -p "$ALPHA_ETAT/$env"
	printf '%s\n' "$version" >"$ALPHA_ETAT/$env/version"
	printf '%s\t%s\t%s\t%s\n' "$(horodater)" "$version" "$action" "${SUDO_USER:-$(id -un)}" >>"$ALPHA_ETAT/$env/historique"
}

controle_public() {
	# Requête réelle à travers Caddy (TLS compris), résolue vers le VPS lui-même.
	local env="$1" domaine code
	domaine="$(valeur_env "$(fichier_env "$env")" "ALPHA_DOMAINE_$(printf '%s' "$env" | tr '[:lower:]' '[:upper:]')")"
	[ -n "$domaine" ] || return 0
	code="$(curl -sS -o /dev/null -w '%{http_code}' -m 15 --resolve "$domaine:443:127.0.0.1" \
		"https://$domaine/api/v1/sante/" 2>/dev/null || true)"
	case "$code" in
		2?? | 404) ok "https://$domaine répond (sonde de santé : HTTP $code)." ;;
		*) avert "https://$domaine ne répond pas correctement (HTTP ${code:-aucune réponse}) : vérifiez Caddy (scripts/deploy.sh journaux proxy)." ;;
	esac
}

cmd_deployer() {
	local env="${1:-}" version="${2:-}" sauvegarde="oui" forcer="non" precedente services
	if [ -z "$env" ] || [ -z "$version" ]; then
		erreur "usage : deployer <recette|prod> <version> [--sans-sauvegarde] [--forcer]"
	fi
	shift 2
	while [ $# -gt 0 ]; do
		case "$1" in
			--sans-sauvegarde) sauvegarde="non" ;;
			--forcer) forcer="oui" ;;
			*) erreur "option inconnue : $1" ;;
		esac
		shift
	done
	verifier_env_nom "$env"
	verifier_docker
	verrouiller
	verifier_fichier_env "$env"
	image_existe "alpha-backend:$version" || erreur "image alpha-backend:$version absente : scripts/deploy.sh construire <tag>."
	image_existe "alpha-frontend:$version" || erreur "image alpha-frontend:$version absente : scripts/deploy.sh construire <tag>."
	docker network inspect "alpha-$env-web" >/dev/null 2>&1 || erreur "réseau alpha-$env-web absent : scripts/deploy.sh reseaux."

	if [ "$env" = "prod" ] && [ "$forcer" != "oui" ]; then
		grep -qP "^\S+\t\Q$version\E\t" "$ALPHA_ETAT/recette/historique" 2>/dev/null ||
			erreur "la version $version n'a jamais été déployée en recette. Validez-la d'abord en recette (ou --forcer, à justifier)."
	fi

	export ALPHA_VERSION="$version"
	precedente="$(version_deployee "$env")"
	info "Déploiement de $version sur $env (version en service : ${precedente:-aucune})"

	# 1. Sauvegarde préalable (si une base existe déjà).
	if [ -n "$(conteneur_service "alpha-$env" db)" ]; then
		if [ "$sauvegarde" = "oui" ]; then
			info "Sauvegarde avant déploiement"
			"$ALPHA_RACINE/scripts/sauvegarde.sh" "$env" --motif avant-deploiement ||
				erreur "sauvegarde impossible : déploiement annulé (--sans-sauvegarde pour passer outre, à vos risques)."
		else
			avert "déploiement SANS sauvegarde préalable."
		fi
	fi

	# 2. Infrastructure (base, Redis) puis migrations, AVANT de toucher à l'application.
	info "Démarrage de la base et de Redis"
	compose_env "$env" up -d --wait --wait-timeout 180 db redis
	info "Migrations (alpha_owner)"
	if ! compose_env "$env" run --rm migrate; then
		erreur "migrations en échec : l'application en service (${precedente:-aucune}) n'a pas été modifiée. Voir docs/ops/deploiement.md § 7."
	fi

	# 3. Application (sans relancer migrate).
	services="$(services_appli "$env")"
	info "Démarrage de l'application : $services"
	# shellcheck disable=SC2086  # liste de services
	if ! compose_env "$env" up -d --no-deps --remove-orphans --wait --wait-timeout 300 $services; then
		compose_env "$env" ps -a >&2 || true
		if [ -n "$precedente" ] && [ "$precedente" != "$version" ]; then
			avert "démarrage en échec : retour automatique à $precedente."
			export ALPHA_VERSION="$precedente"
			# shellcheck disable=SC2086
			compose_env "$env" up -d --no-deps --wait --wait-timeout 300 $services ||
				avert "le retour à $precedente a lui aussi échoué : intervention manuelle (scripts/deploy.sh journaux $env)."
			enregistrer_version "$env" "$precedente" "retour-auto"
		fi
		erreur "le déploiement de $version sur $env a échoué."
	fi
	enregistrer_version "$env" "$version" "deploiement"
	ok "$env en version $version."
	controle_public "$env"
}

cmd_retour() {
	local env="${1:-}" cible="${2:-}" actuelle services
	verifier_env_nom "$env"
	verifier_docker
	verrouiller
	verifier_fichier_env "$env"
	actuelle="$(version_deployee "$env")"
	if [ -z "$cible" ]; then
		# Dernière version de l'historique différente de la version actuelle.
		cible="$(awk -F'\t' -v v="$actuelle" '$2 != v { d = $2 } END { print d }' "$ALPHA_ETAT/$env/historique" 2>/dev/null || true)"
		[ -n "$cible" ] || erreur "aucune version précédente dans l'historique de $env."
	fi
	image_existe "alpha-backend:$cible" || erreur "image alpha-backend:$cible absente."
	image_existe "alpha-frontend:$cible" ||
		erreur "images de la version $cible absentes (supprimées par « nettoyer » ?) : scripts/deploy.sh construire $cible."
	avert "retour de $env de ${actuelle:-?} à $cible SANS annuler les migrations : valable seulement si les migrations"
	avert "de ${actuelle:-?} sont rétrocompatibles (règle « étendre puis contracter », docs/ops/deploiement.md § 6). Sinon, restaurer la"
	avert "sauvegarde « avant-deploiement » (docs/ops/deploiement.md § 8)."
	export ALPHA_VERSION="$cible"
	services="$(services_appli "$env")"
	# shellcheck disable=SC2086
	compose_env "$env" up -d --no-deps --wait --wait-timeout 300 $services
	enregistrer_version "$env" "$cible" "retour"
	ok "$env revenu en version $cible."
	controle_public "$env"
}

# --- proxy ------------------------------------------------------------------------------
cmd_proxy() {
	local env var domaine_env domaine_caddy
	verifier_docker
	verifier_fichier_env caddy
	local r
	for r in alpha-prod-web alpha-recette-web; do
		docker network inspect "$r" >/dev/null 2>&1 || erreur "réseau $r absent : scripts/deploy.sh reseaux."
	done
	# Cohérence des domaines entre .env.caddy et .env.<env>.
	for env in recette prod; do
		[ -f "$(fichier_env "$env")" ] || continue
		var="ALPHA_DOMAINE_$(printf '%s' "$env" | tr '[:lower:]' '[:upper:]')"
		domaine_env="$(valeur_env "$(fichier_env "$env")" "$var")"
		domaine_caddy="$(valeur_env "$(fichier_env caddy)" "$var")"
		[ "$domaine_env" = "$domaine_caddy" ] ||
			erreur "$var diffère entre .env.$env ($domaine_env) et .env.caddy ($domaine_caddy)."
	done
	info "Validation du Caddyfile"
	compose_proxy run --rm --no-deps -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null ||
		erreur "Caddyfile invalide : rien n'a été modifié."
	compose_proxy up -d --wait --wait-timeout 120
	# Prise en compte d'un Caddyfile modifié sans redémarrer (aucune coupure).
	compose_proxy exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
	ok "Caddy démarré et configuration chargée."
}

# --- manage -------------------------------------------------------------------------------
cmd_manage() {
	local env="${1:-}"
	verifier_env_nom "$env"
	shift
	[ $# -gt 0 ] || erreur "usage : manage <recette|prod> <commande Django> [arguments]"
	verifier_docker
	verifier_fichier_env "$env"
	ALPHA_VERSION="$(version_deployee "$env")"
	[ -n "$ALPHA_VERSION" ] || erreur "aucune version déployée sur $env."
	export ALPHA_VERSION
	local tty=()
	if ! { [ -t 0 ] && [ -t 1 ]; }; then tty=(-T); fi
	# Service migrate : seule connexion alpha_owner (commandes d'exploitation, § 3.1).
	compose_env "$env" run --rm --no-deps ${tty[@]+"${tty[@]}"} migrate python manage.py "$@"
}

# --- etat / journaux / nettoyer -------------------------------------------------------------
cmd_etat() {
	verifier_docker
	local env
	for env in recette prod; do
		printf '\n== %s : version %s\n' "$env" "$(version_deployee "$env" | sed 's/^$/(aucune)/')"
		if [ -f "$ALPHA_ETAT/$env/historique" ]; then
			tail -n 5 "$ALPHA_ETAT/$env/historique" | sed 's/^/   /'
		fi
		docker ps -a --filter "label=com.docker.compose.project=alpha-$env" \
			--format '   {{.Names}}\t{{.Status}}\t{{.Image}}'
	done
	printf '\n== proxy\n'
	docker ps -a --filter "label=com.docker.compose.project=alpha-proxy" --format '   {{.Names}}\t{{.Status}}\t{{.Image}}'
	printf '\n== disque\n'
	df -h / | sed 's/^/   /'
	docker system df | sed 's/^/   /'
}

cmd_journaux() {
	local cible="${1:-}"
	shift || true
	verifier_docker
	case "$cible" in
		proxy) compose_proxy logs -f --tail 200 "$@" ;;
		recette | prod)
			ALPHA_VERSION="$(version_deployee "$cible")"
			export ALPHA_VERSION="${ALPHA_VERSION:-inconnue}"
			compose_env "$cible" logs -f --tail 200 "$@"
			;;
		*) erreur "usage : journaux <recette|prod|proxy> [service…]" ;;
	esac
}

cmd_nettoyer() {
	local garder="${1:-5}" proteger tag
	[[ "$garder" =~ ^[0-9]+$ ]] || erreur "usage : nettoyer [N]"
	verifier_docker
	verrouiller
	# Versions protégées : en service + N dernières de chaque historique.
	proteger="$(
		{
			version_deployee recette
			version_deployee prod
			for env in recette prod; do
				[ -f "$ALPHA_ETAT/$env/historique" ] && cut -f2 "$ALPHA_ETAT/$env/historique" | awk '!vu[$0]++' | tail -n "$garder"
			done
		} | sort -u
	)"
	for tag in $(docker image ls --format '{{.Tag}}' alpha-backend | sort -u) $(docker image ls --format '{{.Tag}}' alpha-frontend | sort -u); do
		[ "$tag" = "dev" ] && continue
		grep -qx -- "$tag" <<<"$proteger" && continue
		info "suppression des images de la version $tag"
		docker image rm "alpha-backend:$tag" "alpha-frontend:$tag" >/dev/null 2>&1 || true
	done
	docker image prune -f >/dev/null
	docker builder prune -f --filter until=168h >/dev/null
	ok "nettoyage terminé (versions conservées : $(tr '\n' ' ' <<<"$proteger"))."
}

# --- Aiguillage ----------------------------------------------------------------------------
commande="${1:-help}"
shift || true
case "$commande" in
	secrets) cmd_secrets "$@" ;;
	reseaux) cmd_reseaux ;;
	construire) cmd_construire "$@" ;;
	deployer) cmd_deployer "$@" ;;
	retour) cmd_retour "$@" ;;
	proxy) cmd_proxy ;;
	manage) cmd_manage "$@" ;;
	etat) cmd_etat ;;
	journaux) cmd_journaux "$@" ;;
	nettoyer) cmd_nettoyer "$@" ;;
	help | -h | --help) aide ;;
	*)
		aide
		erreur "commande inconnue : $commande"
		;;
esac
