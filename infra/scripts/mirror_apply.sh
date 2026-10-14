#!/usr/bin/env bash
# Run inside the Mac's Cowork VM (device_bash) after a new bundle is committed.
# Applies the cloud sandbox's git history to the mirrored repo, then checks the
# working tree out to match. Idempotent.
set -euo pipefail
cd "$HOME/mnt/fello-pulse"
git fetch "$PWD/pulse.bundle" 'refs/heads/*:refs/remotes/sandbox/*' --force
git reset --hard refs/remotes/sandbox/main
git log --oneline | head -5
