#!/usr/bin/env bash
#
# Starts Scrapyd, deploys the price_monitor project into it as an egg, then
# hands control back to Scrapyd so it stays PID 1's foreground process.
#
# Why deploy on startup: Scrapyd only knows how to run projects that have been
# uploaded to it as eggs (via addversion.json / scrapyd-deploy). The project
# code is baked into the image, but it still has to be packaged and registered
# with the running daemon — that's what `scrapyd-deploy` does here.
set -euo pipefail

PROJECT="price_monitor"

# Start Scrapyd from a neutral directory (NOT /app) so it doesn't read the
# project's scrapy.cfg and expose a phantom "default" project run from source.
# Config comes from /etc/scrapyd/scrapyd.conf (baked in by the Dockerfile);
# eggs_dir/items_dir there are absolute, so cwd doesn't matter to the daemon.
mkdir -p /var/lib/scrapyd
cd /var/lib/scrapyd
scrapyd &
SCRAPYD_PID=$!

# Wait for the HTTP API to accept connections before deploying.
echo "Waiting for scrapyd to come up..."
for _ in $(seq 1 30); do
    if curl -sf http://localhost:6800/daemonstatus.json >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "Deploying '${PROJECT}' to scrapyd..."
# Build/deploy the egg from the project root, where scrapy.cfg lives.
( cd /app && scrapyd-deploy -p "${PROJECT}" )

echo "scrapyd ready — spiders deployable via schedule.json"

# Keep Scrapyd in the foreground; forward termination signals to it.
trap 'kill -TERM "${SCRAPYD_PID}"' TERM INT
wait "${SCRAPYD_PID}"
