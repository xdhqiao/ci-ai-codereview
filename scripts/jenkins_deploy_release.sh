#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
Usage: jenkins_deploy_release.sh \
  --host HOST --port PORT --root ABSOLUTE_PATH --environment NAME \
  --archive FILE --checksum FILE --image IMAGE --commit FULL_SHA

Required environment variables:
  SSH_KEY_FILE    Jenkins temporary SSH private-key file
  SSH_USER        Remote deployment user
  SSH_KNOWN_HOSTS Jenkins managed known_hosts file
EOF
}

host=""
port="22"
deploy_root=""
deploy_environment=""
archive=""
checksum=""
image=""
commit=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host) host=${2:-}; shift 2 ;;
        --port) port=${2:-}; shift 2 ;;
        --root) deploy_root=${2:-}; shift 2 ;;
        --environment) deploy_environment=${2:-}; shift 2 ;;
        --archive) archive=${2:-}; shift 2 ;;
        --checksum) checksum=${2:-}; shift 2 ;;
        --image) image=${2:-}; shift 2 ;;
        --commit) commit=${2:-}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

: "${SSH_KEY_FILE:?SSH_KEY_FILE is required}"
: "${SSH_USER:?SSH_USER is required}"
: "${SSH_KNOWN_HOSTS:?SSH_KNOWN_HOSTS is required}"
[ -f "$SSH_KEY_FILE" ] || { echo "SSH key not found: $SSH_KEY_FILE" >&2; exit 2; }
[ -f "$SSH_KNOWN_HOSTS" ] || { echo "known_hosts not found: $SSH_KNOWN_HOSTS" >&2; exit 2; }
[ -f "$archive" ] || { echo "Archive not found: $archive" >&2; exit 2; }
[ -f "$checksum" ] || { echo "Checksum not found: $checksum" >&2; exit 2; }

case "$host" in *[!A-Za-z0-9._-]*|'') echo "Invalid deployment host" >&2; exit 2 ;; esac
case "$port" in *[!0-9]*|'') echo "Invalid SSH port" >&2; exit 2 ;; esac
case "$deploy_root" in /*) ;; *) echo "Deployment root must be absolute" >&2; exit 2 ;; esac
case "$deploy_root" in *[!A-Za-z0-9_./-]*) echo "Invalid deployment root" >&2; exit 2 ;; esac
case "$deploy_environment" in *[!a-z0-9-]*|'') echo "Invalid deployment environment" >&2; exit 2 ;; esac
case "$image" in *[!A-Za-z0-9._:/@-]*|'') echo "Invalid image reference" >&2; exit 2 ;; esac
case "$commit" in *[!0-9a-f]*|'') echo "Invalid commit" >&2; exit 2 ;; esac
[ "${#commit}" -eq 40 ] || { echo "Commit must be a full 40-character SHA" >&2; exit 2; }

archive_name="ci-ai-codereview-$commit.tar.gz"
checksum_name="$archive_name.sha256"
incoming_dir="$deploy_root/incoming/$commit"
release_dir="$deploy_root/releases/$commit"
remote="$SSH_USER@$host"

ssh -i "$SSH_KEY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes \
    -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS" -p "$port" "$remote" \
    "mkdir -p '$incoming_dir' '$deploy_root/releases' '$deploy_root/shared'"
scp -i "$SSH_KEY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes \
    -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS" -P "$port" \
    "$archive" "$remote:$incoming_dir/$archive_name"
scp -i "$SSH_KEY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes \
    -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS" -P "$port" \
    "$checksum" "$remote:$incoming_dir/$checksum_name"

ssh -i "$SSH_KEY_FILE" -o BatchMode=yes -o IdentitiesOnly=yes \
    -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS" -p "$port" "$remote" "
    set -eu
    cd '$incoming_dir'
    sha256sum -c '$checksum_name'
    if [ ! -d '$release_dir' ]; then
        temporary_release='$deploy_root/releases/.$commit.tmp'
        rm -rf \"\$temporary_release\"
        mkdir -p \"\$temporary_release\"
        tar -xzf '$archive_name' -C \"\$temporary_release\"
        mv \"\$temporary_release\" '$release_dir'
    fi
    chmod +x '$release_dir/deploy/blue_green_deploy.sh'
    DEPLOY_ROOT='$deploy_root' DEPLOY_ENV='$deploy_environment' \
        '$release_dir/deploy/blue_green_deploy.sh' '$image' '$commit'
"
