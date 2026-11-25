#!/bin/sh
# Publie la table ref.communes dans GeoServer via l'API REST.
# Idempotent : peut être relancé après chaque chargement pour recalculer l'emprise.
set -eu

: "${GEOSERVER_URL:=http://geoserver:8080/geoserver}"
: "${GEOSERVER_ADMIN_USER:?GEOSERVER_ADMIN_USER manquant}"
: "${GEOSERVER_ADMIN_PASSWORD:?GEOSERVER_ADMIN_PASSWORD manquant}"
: "${GEOSERVER_DB_PASSWORD:?GEOSERVER_DB_PASSWORD manquant}"
: "${POSTGRES_DB:=sig}"

WORKSPACE="${GEOSERVER_WORKSPACE:-sig}"
STORE="${GEOSERVER_DATASTORE:-postgis_ref}"
LAYER="communes"
REST="$GEOSERVER_URL/rest"

# Le mot de passe est inséré tel quel dans un document JSON.
case "$GEOSERVER_DB_PASSWORD" in
    *\"* | *\\*)
        echo "GEOSERVER_DB_PASSWORD ne doit contenir ni guillemet ni antislash" >&2
        exit 1
        ;;
esac

existe() {
    code=$(curl -sS -o /dev/null -w '%{http_code}' \
        -u "$GEOSERVER_ADMIN_USER:$GEOSERVER_ADMIN_PASSWORD" \
        -H 'Accept: application/json' "$1")
    [ "$code" = "200" ]
}

envoyer() {
    methode=$1
    url=$2
    corps=$3
    code=$(curl -sS -o /tmp/reponse -w '%{http_code}' \
        -u "$GEOSERVER_ADMIN_USER:$GEOSERVER_ADMIN_PASSWORD" \
        -X "$methode" -H 'Content-Type: application/json' -d "$corps" "$url")
    case "$code" in
        200 | 201) ;;
        *)
            echo "ECHEC $methode $url (HTTP $code)" >&2
            cat /tmp/reponse >&2
            echo >&2
            exit 1
            ;;
    esac
}

if existe "$REST/workspaces/$WORKSPACE"; then
    echo "Espace de travail '$WORKSPACE' déjà présent"
else
    envoyer POST "$REST/workspaces" "{\"workspace\":{\"name\":\"$WORKSPACE\"}}"
    echo "Espace de travail '$WORKSPACE' créé"
fi

if existe "$REST/workspaces/$WORKSPACE/datastores/$STORE"; then
    echo "Entrepôt '$STORE' déjà présent"
else
    envoyer POST "$REST/workspaces/$WORKSPACE/datastores" "{
      \"dataStore\": {
        \"name\": \"$STORE\",
        \"enabled\": true,
        \"connectionParameters\": {
          \"entry\": [
            {\"@key\": \"dbtype\",   \"\$\": \"postgis\"},
            {\"@key\": \"host\",     \"\$\": \"postgis\"},
            {\"@key\": \"port\",     \"\$\": \"5432\"},
            {\"@key\": \"database\", \"\$\": \"$POSTGRES_DB\"},
            {\"@key\": \"schema\",   \"\$\": \"ref\"},
            {\"@key\": \"user\",     \"\$\": \"geoserver_ro\"},
            {\"@key\": \"passwd\",   \"\$\": \"$GEOSERVER_DB_PASSWORD\"},
            {\"@key\": \"Expose primary keys\", \"\$\": \"true\"}
          ]
        }
      }
    }"
    echo "Entrepôt '$STORE' créé (rôle geoserver_ro, lecture seule)"
fi

TYPES="$REST/workspaces/$WORKSPACE/datastores/$STORE/featuretypes"
if existe "$TYPES/$LAYER"; then
    envoyer PUT "$TYPES/$LAYER?recalculate=nativebbox,latlonbbox" \
        "{\"featureType\":{\"name\":\"$LAYER\",\"enabled\":true}}"
    echo "Couche '$WORKSPACE:$LAYER' déjà publiée, emprise recalculée"
else
    envoyer POST "$TYPES" \
        "{\"featureType\":{\"name\":\"$LAYER\",\"nativeName\":\"$LAYER\",\"title\":\"Communes (IGN ADMIN EXPRESS)\",\"srs\":\"EPSG:2154\"}}"
    echo "Couche '$WORKSPACE:$LAYER' publiée"
fi
