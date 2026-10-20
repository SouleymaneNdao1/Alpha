#!/usr/bin/env bash
# Génère les secrets de test d'un job CI et les exporte dans $GITHUB_ENV (masqués dans les journaux).
# Aucun secret réel : tout est tiré au hasard à chaque exécution et disparaît avec le job.
# Usage : env-ci.sh <nom de la base>
set -Eeuo pipefail
base="${1:?nom de la base}"

alea() { openssl rand -hex 16; }
proprietaire="$(alea)"; applicatif="$(alea)"; django="$(alea)$(alea)"; poivre="$(alea)$(alea)"
chiffrement="$(openssl rand -base64 32 | tr '+/' '-_')"
for valeur in "$proprietaire" "$applicatif" "$django" "$poivre" "$chiffrement"; do echo "::add-mask::$valeur"; done

{
	echo "ALPHA_OWNER_PASSWORD=$proprietaire"
	echo "ALPHA_APP_PASSWORD=$applicatif"
	echo "ALPHA_OWNER_CREATEDB=true"
	echo "ALPHA_DB_NAME=$base"
	echo "DJANGO_SECRET_KEY=$django"
	echo "ALPHA_HMAC_POIVRE=$poivre"
	echo "ALPHA_CLES_CHIFFREMENT=$chiffrement"
	echo "ALPHA_DB_APP_ROLE=alpha_app"
	echo "DATABASE_URL=postgres://alpha_app:$applicatif@127.0.0.1:5432/$base"
	echo "DATABASE_URL_OWNER=postgres://alpha_owner:$proprietaire@127.0.0.1:5432/$base"
	echo "REDIS_URL=redis://127.0.0.1:6379/0"
	echo "CELERY_BROKER_URL=redis://127.0.0.1:6379/1"
	echo "EMAIL_HOST=127.0.0.1"
	echo "EMAIL_PORT=1025"
	echo "ALPHA_URL_FRONTEND=http://localhost:3000"
	echo "TZ=Africa/Dakar"
	# Connexion psql du script d'initialisation des rôles (superutilisateur du service postgres).
	echo "PGHOST=127.0.0.1"
	echo "PGPASSWORD=postgres"
	echo "POSTGRES_USER=postgres"
	echo "POSTGRES_DB=postgres"
} >> "$GITHUB_ENV"
