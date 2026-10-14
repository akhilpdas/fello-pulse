#!/usr/bin/env bash
# Run inside the Mac's Cowork VM (device_bash) after a new bundle is committed to
# ~/Documents/fello-pulse/pulse.bundle. Applies the cloud sandbox's history to the
# mirror and checks the working tree out to match. Idempotent.
#
# Note on the stale-lock guard: git removes its own .lock files, and deletion in a
# connected folder is denied until the user approves it. Without that approval a
# single fetch leaves a lock behind and every later git command fails with
# "File exists", so the guard clears locks this script's own earlier runs left.
set -euo pipefail
cd "${MIRROR:-$HOME/mnt/fello-pulse}"

find .git -maxdepth 2 -name '*.lock' -not -path '.git/refs/*' -delete 2>/dev/null || true

git fetch "$PWD/pulse.bundle" 'refs/heads/*:refs/remotes/sandbox/*' --force
BRANCH="$(git ls-remote --symref "$PWD/pulse.bundle" HEAD 2>/dev/null \
          | awk '/^ref:/{sub("refs/heads/","",$2); print $2; exit}')"
BRANCH="${BRANCH:-main}"
git reset --hard "refs/remotes/sandbox/$BRANCH"
echo "--- mirror now at ---"
git log --oneline | head -5
git status --short
