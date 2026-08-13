#!/bin/bash
# Velxio fresh-build bootstrap script (auto-fetch variant)
# Clones Velxio and builds it with Docker fetching the prebuilt QEMU
# binaries mid-build via QEMU_RELEASE_URL — no manual file staging,
# no license key needed.
set -euo pipefail

REPO_URL="https://github.com/davidmonterocrespo24/velxio.git"
QEMU_RELEASE_URL="https://github.com/ZhadowValker/IoT-Studio/releases/download/qemu-prebuilt-v2"
CLONE_DIR="velxio"

echo "==> Cloning Velxio..."
git clone "$REPO_URL" "$CLONE_DIR"
cd "$CLONE_DIR"

echo "==> Building Velxio (Docker will fetch QEMU binaries from release: $QEMU_RELEASE_URL)..."
docker compose build --build-arg QEMU_RELEASE_URL="$QEMU_RELEASE_URL"

echo "==> Starting Velxio..."
docker compose up -d

echo "==> Waiting for container health..."
sleep 5
docker compose ps

echo ""
echo "Done. Once healthy, open: http://localhost:3080"
echo "Check logs with: docker compose logs -f"
