#!/usr/bin/env bash
# Follow one branch of a repository and apply each new commit to this server.
#
#     follow-branch.sh <state folder>
#
# Runs on the server it deploys to (a test environment following its test branch, or production following main),
# from a systemd timer (follow-branch@.timer), which passes the state folder. The server fetches; nothing on the git
# server can reach it, and the credentials the application needs never leave it. Works with any git server that
# offers a read-only deploy key (GitHub, Gitea, GitLab...).
#
# Settings come from the environment (EnvironmentFile= in follow-branch@.service; see example.env):
#   REPOSITORY     the repository's address: ssh:// or git@... with the deploy key (or file:// for a local one)
#   BRANCH         the branch to follow
#   APPLY          absolute path of IT's command that applies a release: APPLY <release folder> <commit>
#   APPLY_TIMEOUT  optional: seconds APPLY may take before it counts as failed (default 600)
#   KEEP           optional: how many releases to keep (default 3)
#   SSH_KEY, KNOWN_HOSTS  optional: the deploy key and the git server's host keys; by default the unit's
#                  credentials (LoadCredential=deploy-key, known-hosts). Hosts are never trusted on first use.
#
# Each run starts from nothing it kept of git: the commit is fetched into a new temporary repository, unpacked as a
# release (git archive: the files only, no .git, hooks or submodules) and the repository is removed. So code from a
# branch, which APPLY runs, cannot leave anything that changes later fetches.

set -euo pipefail
umask 027

fail() { echo "follow-branch: $*" >&2; exit 2; }

STATE_DIR="${1:-}"
: "${REPOSITORY:?REPOSITORY is not set}"
: "${BRANCH:?BRANCH is not set}"
: "${APPLY:?APPLY is not set}"
KEEP="${KEEP:-3}"
APPLY_TIMEOUT="${APPLY_TIMEOUT:-600}"
if [[ -z "${SSH_KEY:-}" && -n "${CREDENTIALS_DIRECTORY:-}" && -r "$CREDENTIALS_DIRECTORY/deploy-key" ]]; then
    SSH_KEY="$CREDENTIALS_DIRECTORY/deploy-key"
    KNOWN_HOSTS="${KNOWN_HOSTS:-$CREDENTIALS_DIRECTORY/known-hosts}"
fi

[[ "$STATE_DIR" == /* ]] || fail "the state folder must be given as an absolute path"
# The same rules as eunomai-business's branch names: parts of letters, digits, . _ - separated by /.
[[ "$BRANCH" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$ ]] || fail "BRANCH is not a plain branch name"
[[ "$BRANCH" != *..* && "$BRANCH" != *.lock && "$BRANCH" != *. && "$BRANCH" != */.* ]] ||
    fail "BRANCH is not a plain branch name"
[[ "$REPOSITORY" =~ ^(ssh://|file://|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:) ]] ||
    fail "REPOSITORY must be ssh://, user@host:path or file://"
[[ "$APPLY" == /* && -x "$APPLY" ]] || fail "APPLY must be the absolute path of an executable"
case "$APPLY" in "$STATE_DIR"/*) fail "APPLY must not live in the state folder, where the repository's files go" ;; esac
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || fail "KEEP must be a positive number"
[[ "$APPLY_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || fail "APPLY_TIMEOUT must be a number of seconds"

if [[ -n "${SSH_KEY:-}" ]]; then
    for path in "$SSH_KEY" "${KNOWN_HOSTS:-}"; do
        [[ "$path" =~ ^/[A-Za-z0-9/._-]+$ && -r "$path" ]] || fail "SSH_KEY needs KNOWN_HOSTS: plain, readable paths"
    done
    export GIT_SSH_COMMAND="ssh -F /dev/null -i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS"
fi
# Nothing from this server's or this user's git configuration, no prompt, and only the transports named here.
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
git_() {
    git -c protocol.allow=never -c protocol.ssh.allow=always -c protocol.file.allow=always -c core.hooksPath=/dev/null \
        -c transfer.fsckObjects=true -c gc.auto=0 -c maintenance.auto=false "$@"
}

mkdir -p "$STATE_DIR/releases"
exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0  # the last run is still applying

remote="$(git_ ls-remote --end-of-options "$REPOSITORY" "refs/heads/$BRANCH")" || fail "cannot read $BRANCH"
new="${remote%%[[:space:]]*}"
[[ "$new" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || fail "the branch $BRANCH was not found"
release="$STATE_DIR/releases/$new"

[[ "$new" == "$(cat "$STATE_DIR/deployed" 2>/dev/null || true)" ]] && exit 0
if [[ "$(readlink "$STATE_DIR/current" 2>/dev/null || true)" == "$release" ]]; then  # a run stopped right after
    echo "$new" > "$STATE_DIR/deployed"
    exit 0
fi
if [[ "$new" == "$(cat "$STATE_DIR/failed" 2>/dev/null || true)" ]]; then
    echo "follow-branch: skipping $new, which failed to apply; remove $STATE_DIR/failed to try it again"
    exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git_ init -q --bare "$work/repo.git"
git_ -C "$work/repo.git" fetch -q --no-tags --depth 1 --end-of-options "$REPOSITORY" "+refs/heads/$BRANCH:refs/heads/follow"
fetched="$(git_ -C "$work/repo.git" rev-parse --verify -q "refs/heads/follow^{commit}")" || fail "the branch has no commit"
if [[ "$fetched" != "$new" ]]; then  # it moved since it was read: the next run takes the newest
    echo "follow-branch: $BRANCH moved while it was read; trying again on the next run"
    exit 0
fi
rm -rf "$release"
mkdir -p "$release"
git_ -C "$work/repo.git" archive --format=tar "$new" | tar -x --no-same-owner -C "$release"
rm -rf "$work"

echo "follow-branch: applying $BRANCH at $new"
# APPLY gets neither the deploy key nor the lock: what it runs is the branch's code.
if ! env -u REPOSITORY -u SSH_KEY -u KNOWN_HOSTS -u GIT_SSH_COMMAND -u CREDENTIALS_DIRECTORY \
        timeout --kill-after=30 "$APPLY_TIMEOUT" "$APPLY" "$release" "$new" 9>&-; then
    echo "$new" > "$STATE_DIR/failed"
    rm -rf "$release"
    fail "applying $new failed; the previous release stays current, though what APPLY changed before failing (a migration) stays changed"
fi
ln -sfn "$release" "$STATE_DIR/current.new"
mv -Tf "$STATE_DIR/current.new" "$STATE_DIR/current"
echo "$new" > "$STATE_DIR/deployed.new"
mv -f "$STATE_DIR/deployed.new" "$STATE_DIR/deployed"  # restart-on-deploy@.path restarts the application on this
rm -f "$STATE_DIR/failed"
echo "follow-branch: $BRANCH at $new is current"

# Keep the newest releases, never the current one.
find "$STATE_DIR/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2- |
    tail -n +"$((KEEP + 1))" | while read -r old; do
        [[ "$old" == "$release" ]] || rm -rf "$old"
    done
