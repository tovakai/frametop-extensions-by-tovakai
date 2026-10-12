#!/usr/bin/env bash
# Migrate a SOURCE-installed Frametop to the extension-capable development core.
# Keep the original source checkout for a simple, non-destructive rollback.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
UPSTREAM="$HOME/frametop"
CORE="$HOME/frametop-plugin-core"
BACKUPS="$HOME/.local/state/frametop-extensions/migrations"
[[ -z "$(printenv FT_UPSTREAM_DIR 2>/dev/null)" ]] || UPSTREAM="$FT_UPSTREAM_DIR"
[[ -z "$(printenv FT_PLUGIN_CORE_DIR 2>/dev/null)" ]] || CORE="$FT_PLUGIN_CORE_DIR"
[[ -z "$(printenv FT_UPGRADE_BACKUP_ROOT 2>/dev/null)" ]] || BACKUPS="$FT_UPGRADE_BACKUP_ROOT"
FORK=https://github.com/tovakai/frametop.git
BRANCH=rebuild/extension-api
LAUNCHER="$HOME/.local/share/applications/deckard-nested-desktop.desktop"

canonical() {
    python3 -c 'import os,sys;print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$1"
}
UPSTREAM=$(canonical "$UPSTREAM")
CORE=$(canonical "$CORE")
BACKUPS=$(canonical "$BACKUPS")
ROOT=$(canonical "$ROOT")

fail() { printf 'frametop-upgrade: %s\n' "$*" >&2; exit 1; }
[[ "$UPSTREAM" != "$CORE" && "$UPSTREAM" != "$HOME" && "$CORE" != "$HOME" &&
   "$CORE" != "/" && "$UPSTREAM" != "/" ]] || fail "unsafe checkout paths"

usage() {
    cat <<'EOF'
Usage: bash tools/upgrade-from-upstream.sh plan|status|apply|rollback

plan      Read-only summary and prerequisites, safe on any Linux machine.
status    Inspect active Steam desktop launcher and checkouts.
apply     Interactive migration to extension-enabled development Frametop.
rollback  Interactive switch back to the untouched upstream source checkout.

Environment: FT_UPSTREAM_DIR, FT_PLUGIN_CORE_DIR, FT_UPGRADE_BACKUP_ROOT.
Run apply/rollback ON the Steam Frame, from a terminal. Never use sudo.
EOF
}

check_source() {
    command -v git >/dev/null || fail "git is required"
    [[ -f "$UPSTREAM/install.sh" && -f "$UPSTREAM/session/frametop-session.sh" &&
       -f "$UPSTREAM/scripts/_env.sh" ]] ||
       fail "no Frametop source installation at $UPSTREAM (release-image installs not yet supported)"
    [[ -d "$UPSTREAM/.git" || -f "$UPSTREAM/.git" ]] ||
       fail "source checkout must be a Git repository"
    [[ $(git -C "$UPSTREAM" rev-parse --show-toplevel) == "$UPSTREAM" ]] ||
       fail "source checkout root does not match configured directory"
    [[ ! -f "$UPSTREAM/.frametop-release" ]] || fail "release-image installations are not yet supported"
}

check_frame() {
    grep -qx 'ID=steamos' /etc/os-release 2>/dev/null &&
    grep -qE '^VARIANT_ID="?vr"?$' /etc/os-release ||
        fail "apply and rollback must run on the Steam Frame, not a PC"
    [[ $(id -u) != 0 ]] || fail "never run this command as root"
    [[ -t 0 && -t 1 ]] || fail "interactive terminal required for installation and confirmation"
}

owner() {
    local exec_line
    exec_line=$(grep -m 1 '^Exec=' "$LAUNCHER" 2>/dev/null || true)
    case "$exec_line" in
        *"$CORE/session/frametop-session.sh"*) printf 'plugin-core\n' ;;
        *"$UPSTREAM/session/frametop-session.sh"*) printf 'upstream\n' ;;
        "") printf 'unknown\n' ;;
        *) printf 'other\n' ;;
    esac
}

status() {
    printf 'Active launcher: %s\n' "$(owner)"
    if [[ -f "$LAUNCHER" ]]; then
        grep -m 1 '^Exec=' "$LAUNCHER" || true
    fi
    printf 'Upstream source: %s\nPlugin core: %s\n' "$UPSTREAM" "$CORE"
    if [[ -d "$CORE/.git" ]]; then
        git -C "$CORE" log -1 --format='Core head: %h %s'
    fi
}

plan() {
    check_source
    printf 'Original upstream: %s\n' "$UPSTREAM"
    git -C "$UPSTREAM" log -1 --format='Original commit: %h %s'
    printf 'Experimental core: %s\n  %s @ %s\n' "$CORE" "$FORK" "$BRANCH"
    printf 'Extension repository: %s\nCurrent launcher: %s\n' "$ROOT" "$(owner)"
    cat <<'EOF'

apply:
  - Preserves upstream source and Git history without modification.
  - Clones the fork into a separate, checked source directory.
  - Saves local settings into a private, timestamped backup.
  - Runs the official Frametop interactive installer from that directory.
  - Leaves any SteamVR restart to your explicit decision.

rollback:
  - Re-runs the original upstream install.sh (no directory deletions).
  - Leaves settings, legacy profiles, plugin repository, and backup intact.

WARNING: Extension API draft v1 is not device-verified. Spatial Profiles is
read-only and is NOT a replacement for the legacy fork yet.
This is an experimental extension-capable CORE upgrade, not a plugin install.
Release-image upstream installations are currently unsupported.
EOF
}

confirm() {
    local value answer
    value=$1
    printf 'Type %s to continue, or anything else to cancel: ' "$value"
    read -r answer </dev/tty || fail "confirmation unavailable"
    [[ "$answer" == "$value" ]] || fail "cancelled without changing installation"
}

clone_core() {
    if [[ -e "$CORE" || -L "$CORE" ]]; then
        [[ -d "$CORE/.git" ]] || fail "existing plugin core directory is not a Git checkout"
        [[ $(git -C "$CORE" rev-parse --show-toplevel) == "$CORE" ]] ||
            fail "plugin core checkout root differs"
        local remote branch
        remote=$(git -C "$CORE" remote get-url origin)
        case "$remote" in
            "$FORK"|https://github.com/tovakai/frametop|git@github.com:tovakai/frametop.git) ;;
            *) fail "unexpected plugin core remote: $remote" ;;
        esac
        branch=$(git -C "$CORE" branch --show-current)
        [[ "$branch" == "$BRANCH" ]] || fail "plugin core branch is $branch, not $BRANCH"
        [[ -z "$(git -C "$CORE" status --porcelain)" ]] ||
            fail "plugin core has local modifications; commit or stash them first"
        [[ $(owner) != plugin-core ]] || fail "refusing to update an active plugin-core checkout"
        git -C "$CORE" pull --ff-only
    else
        mkdir -p "$(dirname "$CORE")"
        git clone --single-branch --branch "$BRANCH" "$FORK" "$CORE"
    fi
    [[ -x "$CORE/install.sh" ]] || fail "plugin core installer is missing or not executable"
}

backup_config() {
    local folder file
    folder="$BACKUPS/$(date -u +%Y%m%dT%H%M%SZ)"
    [[ ! -e "$folder" ]] || fail "backup directory already exists: $folder"
    mkdir -p "$folder"
    chmod 700 "$BACKUPS" "$folder"
    for file in frametop.conf frametop-layout.json frametop-layout-profiles.json frametop-input.json frametoprc; do
        if [[ -e "$HOME/.config/$file" || -L "$HOME/.config/$file" ]]; then
            cp -a "$HOME/.config/$file" "$folder/$file"
        fi
    done
    [[ ! -d "$HOME/.config/frametop" ]] || cp -a "$HOME/.config/frametop" "$folder/frametop"
    {
        printf 'upstream=%s\ncore=%s\nextensions=%s\n' "$UPSTREAM" "$CORE" "$ROOT"
        git -C "$UPSTREAM" rev-parse HEAD | sed 's/^/upstream_commit=/'
        git -C "$CORE" rev-parse HEAD | sed 's/^/core_commit=/'
    } > "$folder/source.txt"
    printf 'Saved original settings at %s\n' "$folder"
}

apply() {
    check_source
    check_frame
    [[ $(owner) != plugin-core ]] || fail "plugin core is already active"
    plan
    printf '\nThe installer changes the desktop launcher, services and SteamVR pointer driver.\n'
    printf 'Prefer running over SSH or from the stock desktop, not an active Frametop session.\n'
    confirm UPGRADE
    clone_core
    backup_config
    printf '\nRunning official Frametop installer from the isolated extension core...\n'
    if ! (cd "$CORE" && ./install.sh); then
        fail "install failed or was interrupted; original upstream code is intact.
Run this script with rollback to restore upstream installation."
    fi
    printf '\nExtension-capable CORE installed; plugins have NOT been enabled.\n'
    status
}

rollback() {
    check_source
    check_frame
    printf 'Switch back to original upstream at %s\n' "$UPSTREAM"
    printf 'Settings are preserved. The plugin-core checkout is not deleted.\n'
    confirm ROLLBACK
    (cd "$UPSTREAM" && ./install.sh)
    printf 'Upstream installer completed. Restart SteamVR if its installer asks.\n'
    status
}

if [[ $# != 1 ]]; then
    usage >&2
    exit 2
fi
case "$1" in
    plan) plan ;;
    status) status ;;
    apply) apply ;;
    rollback) rollback ;;
    --help|-h|help) usage ;;
    *) usage >&2; exit 2 ;;
esac
