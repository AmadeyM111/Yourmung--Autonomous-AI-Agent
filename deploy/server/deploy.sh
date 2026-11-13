#!/usr/bin/env bash
# Auto-deploy: fast-forward the checkout to origin/<checked-out branch> and restart only what changed.
# Run by yourmung-deploy.timer every 2 minutes. Never touches .env or data/.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec 9>/tmp/yourmung-deploy.lock; flock -n 9 || exit 0
# Deploys the branch that is checked out on the server (normally `deploy`).
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch --quiet origin "$BRANCH"
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && exit 0
CHANGED=$(git diff --name-only "$OLD" "$NEW")
git merge --ff-only "origin/$BRANCH" >/dev/null || { echo "deploy: not a fast-forward, skipping" >&2; exit 1; }
echo "deploy: $OLD -> $NEW"
if echo "$CHANGED" | grep -qE '^(Dockerfile|requirements.*|pyproject.toml|uv.lock)$'; then
  docker compose up -d --build
elif echo "$CHANGED" | grep -qE '^(docker-compose.*\.yml|ouroboros/telegram_bridge_setup\.py|prompts/SYSTEM\.md)$'; then
  docker compose up -d
else
  echo "deploy: no runtime-relevant changes, container not restarted"
fi
if echo "$CHANGED" | grep -q '^deploy/server/tg-socks.service$'; then
  install -m 644 deploy/server/tg-socks.service /etc/systemd/system/tg-socks.service
  systemctl daemon-reload; systemctl restart tg-socks
fi
