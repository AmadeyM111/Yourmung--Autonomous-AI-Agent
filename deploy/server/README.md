# Server deployment

The server runs the stack with `COMPOSE_FILE=docker-compose.yml:docker-compose.server.yml` (set in the untracked `.env`).
`docker-compose.server.yml` carries the SOCKS proxy for Telegram, the pinned network subnet and the patched-file mounts.

Auto-deploy: `yourmung-deploy.timer` runs `deploy.sh` every 2 minutes. It fast-forwards to `origin/main`,
rebuilds the image only when `Dockerfile`, requirements, `pyproject.toml` or `uv.lock` change, recreates the container
only when compose files or the mounted patched files change, and otherwise does nothing. Secrets stay in `.env`.

One-time install on the server:

    cp deploy/server/tg-socks.service deploy/server/yourmung-deploy.service deploy/server/yourmung-deploy.timer /etc/systemd/system/
    systemctl daemon-reload && systemctl enable --now tg-socks yourmung-deploy.timer
