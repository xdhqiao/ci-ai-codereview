#!/bin/sh
set -eu

usage() {
    echo "Usage: blue_green_deploy.sh IMAGE FULL_COMMIT" >&2
}

[ "$#" -eq 2 ] || { usage; exit 2; }
APP_IMAGE=$1
FULL_COMMIT=$2

case "$APP_IMAGE" in *[!A-Za-z0-9._:/@-]*|'') echo "Invalid image reference" >&2; exit 2 ;; esac
case "$FULL_COMMIT" in *[!0-9a-f]*|'') echo "Invalid commit" >&2; exit 2 ;; esac
[ "${#FULL_COMMIT}" -eq 40 ] || { echo "Commit must be a full SHA" >&2; exit 2; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RELEASE_DIR=$(dirname "$SCRIPT_DIR")
DEPLOY_ROOT=${DEPLOY_ROOT:-/opt/ci-ai-codereview}
DEPLOY_ENV=${DEPLOY_ENV:-prod}
SHARED_DIR="$DEPLOY_ROOT/shared"
STATE_DIR="$DEPLOY_ROOT/state"
GATEWAY_CONFIG_DIR="$DEPLOY_ROOT/gateway"
DEPLOY_CONFIG="$SHARED_DIR/deploy.env"

case "$DEPLOY_ROOT" in /*) ;; *) echo "DEPLOY_ROOT must be absolute" >&2; exit 2 ;; esac
case "$DEPLOY_ROOT" in *[!A-Za-z0-9_./-]*) echo "Invalid DEPLOY_ROOT" >&2; exit 2 ;; esac
case "$DEPLOY_ENV" in *[!a-z0-9-]*|'') echo "Invalid DEPLOY_ENV" >&2; exit 2 ;; esac

if [ -f "$DEPLOY_CONFIG" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$DEPLOY_CONFIG"
    set +a
fi

APP_ENV_FILE=${APP_ENV_FILE:-$SHARED_DIR/app.env}
APP_NETWORK=${APP_NETWORK:-ci-ai-codereview-$DEPLOY_ENV}
HEALTH_TIMEOUT_SECONDS=${HEALTH_TIMEOUT_SECONDS:-180}
APP_STOP_GRACE_PERIOD=${APP_STOP_GRACE_PERIOD:-360s}
DEPLOY_LOCK_TIMEOUT_SECONDS=${DEPLOY_LOCK_TIMEOUT_SECONDS:-900}
PUBLIC_BIND_ADDRESS=${PUBLIC_BIND_ADDRESS:-0.0.0.0}
PUBLIC_PORT=${PUBLIC_PORT:-8000}
GATEWAY_IMAGE=${GATEWAY_IMAGE:-nginx:1.27-alpine}

: "${CODE_REPOSITORY_HOST_ROOT:?Set CODE_REPOSITORY_HOST_ROOT in $DEPLOY_CONFIG}"
case "$DEPLOY_LOCK_TIMEOUT_SECONDS" in
    *[!0-9]*|'') echo "DEPLOY_LOCK_TIMEOUT_SECONDS must be a positive integer" >&2; exit 2 ;;
esac
[ -r "$APP_ENV_FILE" ] || { echo "Missing app env file: $APP_ENV_FILE" >&2; exit 2; }
[ -d "$CODE_REPOSITORY_HOST_ROOT" ] || {
    echo "Repository root does not exist: $CODE_REPOSITORY_HOST_ROOT" >&2
    exit 2
}

mkdir -p "$SHARED_DIR" "$STATE_DIR" "$GATEWAY_CONFIG_DIR"
command -v flock >/dev/null 2>&1 || {
    echo "flock is required on the deployment server" >&2
    exit 2
}
exec 9>"$STATE_DIR/deploy.lock"
flock -w "$DEPLOY_LOCK_TIMEOUT_SECONDS" 9 || {
    echo "Another deployment still holds $STATE_DIR/deploy.lock" >&2
    exit 1
}
docker network inspect "$APP_NETWORK" >/dev/null 2>&1 || docker network create "$APP_NETWORK" >/dev/null

active_slot=""
if [ -s "$STATE_DIR/active-slot" ]; then
    active_slot=$(cat "$STATE_DIR/active-slot")
fi
case "$active_slot" in
    blue) next_slot=green ;;
    green) next_slot=blue ;;
    "") next_slot=blue ;;
    *) echo "Invalid active slot state: $active_slot" >&2; exit 2 ;;
esac

slot_project="ci-ai-codereview-$DEPLOY_ENV-$next_slot"
gateway_project="ci-ai-codereview-$DEPLOY_ENV-gateway"
new_web="ci-ai-codereview-$DEPLOY_ENV-web-$next_slot"
new_worker="ci-ai-codereview-$DEPLOY_ENV-worker-$next_slot"
gateway="ci-ai-codereview-$DEPLOY_ENV-gateway"

export APP_IMAGE APP_ENV_FILE APP_NETWORK APP_STOP_GRACE_PERIOD CODE_REPOSITORY_HOST_ROOT
export DEPLOY_ENV GATEWAY_CONFIG_DIR GATEWAY_IMAGE PUBLIC_BIND_ADDRESS PUBLIC_PORT
DEPLOY_SLOT=$next_slot
export DEPLOY_SLOT

wait_for_healthy() {
    container=$1
    elapsed=0
    while [ "$elapsed" -lt "$HEALTH_TIMEOUT_SECONDS" ]; do
        status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
            "$container" 2>/dev/null || true)
        if [ "$status" = "healthy" ]; then
            return 0
        fi
        if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
            break
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "Container did not become healthy: $container" >&2
    docker logs --tail 100 "$container" >&2 || true
    return 1
}

rollback_new_slot() {
    docker compose --project-name "$slot_project" --file "$SCRIPT_DIR/compose.slot.yml" \
        down --remove-orphans >/dev/null 2>&1 || true
}

docker compose --project-name "$slot_project" --file "$SCRIPT_DIR/compose.slot.yml" pull web worker
docker compose --project-name "$slot_project" --file "$SCRIPT_DIR/compose.slot.yml" \
    up --detach --no-deps web worker
wait_for_healthy "$new_web" || { rollback_new_slot; exit 1; }
wait_for_healthy "$new_worker" || { rollback_new_slot; exit 1; }

candidate_config="$GATEWAY_CONFIG_DIR/.active.conf.$FULL_COMMIT"
active_config="$GATEWAY_CONFIG_DIR/active.conf"
backup_config="$GATEWAY_CONFIG_DIR/.active.conf.previous"
cat > "$candidate_config" <<EOF
upstream code_review_backend {
    server $new_web:8000;
    keepalive 32;
}

server {
    listen 8000;
    server_name _;
    client_max_body_size 10m;

    location / {
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_send_timeout 900s;
        proxy_read_timeout 900s;
        proxy_pass http://code_review_backend;
    }
}
EOF

gateway_exists=false
gateway_started=false
if docker inspect "$gateway" >/dev/null 2>&1; then
    gateway_exists=true
    if [ -f "$active_config" ]; then
        cp "$active_config" "$backup_config"
    fi
fi
mv "$candidate_config" "$active_config"

if [ "$gateway_exists" = "true" ]; then
    if ! docker exec "$gateway" nginx -t || ! docker exec "$gateway" nginx -s reload; then
        if [ -f "$backup_config" ]; then
            mv "$backup_config" "$active_config"
        else
            rm -f "$active_config"
        fi
        rollback_new_slot
        exit 1
    fi
else
    if ! docker compose --project-name "$gateway_project" --file "$SCRIPT_DIR/compose.gateway.yml" \
        up --detach; then
        rm -f "$active_config"
        rollback_new_slot
        exit 1
    fi
    gateway_started=true
    if ! wait_for_healthy "$gateway"; then
        docker compose --project-name "$gateway_project" --file "$SCRIPT_DIR/compose.gateway.yml" \
            down --remove-orphans >/dev/null 2>&1 || true
        rm -f "$active_config"
        rollback_new_slot
        exit 1
    fi
fi

if ! docker exec "$gateway" wget -q -T 10 -O - http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
    echo "Gateway verification failed; restoring the previous upstream" >&2
    if [ -f "$backup_config" ]; then
        mv "$backup_config" "$active_config"
        docker exec "$gateway" nginx -t
        docker exec "$gateway" nginx -s reload
    elif [ "$gateway_started" = "true" ]; then
        docker compose --project-name "$gateway_project" --file "$SCRIPT_DIR/compose.gateway.yml" \
            down --remove-orphans >/dev/null 2>&1 || true
        rm -f "$active_config"
    fi
    rollback_new_slot
    exit 1
fi

if [ -s "$STATE_DIR/active-image" ]; then
    cp "$STATE_DIR/active-image" "$STATE_DIR/previous-image"
fi
printf '%s\n' "$next_slot" > "$STATE_DIR/active-slot"
printf '%s\n' "$APP_IMAGE" > "$STATE_DIR/active-image"
printf '%s\n' "$FULL_COMMIT" > "$STATE_DIR/active-commit"
ln -sfn "$RELEASE_DIR" "$DEPLOY_ROOT/current"

if [ -n "$active_slot" ]; then
    old_project="ci-ai-codereview-$DEPLOY_ENV-$active_slot"
    old_worker="ci-ai-codereview-$DEPLOY_ENV-worker-$active_slot"
    old_web="ci-ai-codereview-$DEPLOY_ENV-web-$active_slot"
    DEPLOY_SLOT=$active_slot
    export DEPLOY_SLOT
    docker compose --project-name "$old_project" --file "$SCRIPT_DIR/compose.slot.yml" \
        stop worker >/dev/null 2>&1 || docker stop "$old_worker" >/dev/null 2>&1 || true
    echo "Previous web slot remains available for connection draining and rollback: $old_web"
fi

echo "Deployment completed: environment=$DEPLOY_ENV slot=$next_slot commit=$FULL_COMMIT image=$APP_IMAGE"
