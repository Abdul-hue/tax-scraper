#!/bin/bash

# ─────────────────────────────────────────────────────────────────────────────
# IIR Scraper Tool — Standalone Deployment Script
# Usage: ./deploy-iir.sh
#
# Deploys the Individual Insolvency Register scraper as its own container,
# completely isolated from the existing staging/production scraper-tool
# deployments. Different image name, different container name, different
# ports — nothing on the shared host other than this tool is touched.
#
# Requires .env.deploy (in this dir, parent dir, or backend/) with:
#   SSH_HOST, SSH_USER, SSH_KEY_PATH, SSH_PASSWORD
#   GIT_USERNAME, GIT_PASSWORD, GIT_REPO_URL
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Hardcoded configuration for the IIR tool ─────────────────────────────────
IMAGE_NAME="iir-scraper-tool"
TARGET_DIR="iir-scraper-tool"
BRANCH="IIR-scraper"
FRONTEND_PORT=3414
BACKEND_PORT=7889
COMPOSE_FILE_LOCAL="docker-compose.iir.yml"

# ── Load .env.deploy ─────────────────────────────────────────────────────────
DOTENV_DEPLOY=".env.deploy"
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "../.env.deploy" ]; then
    DOTENV_DEPLOY="../.env.deploy"
fi
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "backend/.env.deploy" ]; then
    DOTENV_DEPLOY="backend/.env.deploy"
fi

if [ -f "$DOTENV_DEPLOY" ]; then
    echo "📖 Loading deployment secrets from $DOTENV_DEPLOY..."
    eval $(python3 -c "
from pathlib import Path
import sys
content = Path(sys.argv[1]).read_text()
for line in content.splitlines():
    line = line.strip()
    if not line or line.startswith('#'): continue
    if '=' in line:
        k, v = line.split('=', 1)
        v_escaped = v.replace(\"'\", \"'\\\\''\")
        print(f'export {k}=\\'{v_escaped}\\'')
" "$DOTENV_DEPLOY")
else
    echo "❌ Error: Could not find .env.deploy in current, parent, or backend/ directory."
    exit 1
fi

# ── Validate required secrets ────────────────────────────────────────────────
if [[ -z "$SSH_HOST" || -z "$SSH_USER" || -z "$SSH_KEY_PATH" || -z "$GIT_REPO_URL" || -z "$SSH_PASSWORD" ]]; then
    echo "❌ Error: Required secrets (SSH_HOST, SSH_USER, SSH_KEY_PATH, GIT_REPO_URL, SSH_PASSWORD) not found."
    exit 1
fi

GIT_AUTH_URL=$(echo "$GIT_REPO_URL" | sed "s|https://|https://${GIT_USERNAME}:${GIT_PASSWORD}@|")

echo ""
echo "🚀 Deploying [IIR-scraper] to $SSH_USER@$SSH_HOST"
echo "   Branch        : $BRANCH"
echo "   Image         : $IMAGE_NAME"
echo "   Container     : $IMAGE_NAME"
echo "   Frontend Port : $FRONTEND_PORT"
echo "   Backend Port  : $BACKEND_PORT"
echo "   Compose file  : $COMPOSE_FILE_LOCAL"
echo ""
echo "   ⚠️  This deploy is fully scoped to the '$IMAGE_NAME' container."
echo "   ⚠️  Existing staging/production scraper containers are NOT touched."
echo ""

# ── Sync the IIR compose file to the server ──────────────────────────────────
if [ ! -f "$COMPOSE_FILE_LOCAL" ]; then
    echo "❌ Error: $COMPOSE_FILE_LOCAL not found in current directory."
    exit 1
fi

echo "📤 Syncing $COMPOSE_FILE_LOCAL to server (as docker-compose.yml in $TARGET_DIR)..."
scp -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no \
    "$COMPOSE_FILE_LOCAL" "$SSH_USER@$SSH_HOST:/tmp/iir-docker-compose.yml"

# ── Transfer sudo password via a temp file ───────────────────────────────────
PASS_TMPFILE=$(mktemp /tmp/iir_deploy_pass.XXXXXX)
printf '%s' "$SSH_PASSWORD" > "$PASS_TMPFILE"
chmod 600 "$PASS_TMPFILE"
scp -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no \
    "$PASS_TMPFILE" "$SSH_USER@$SSH_HOST:/tmp/.iir_sudo_pass"
rm -f "$PASS_TMPFILE"

# ── Ensure user is in docker group ───────────────────────────────────────────
echo "🔧 Ensuring $SSH_USER is in docker group on remote server..."
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" \
    "cat /tmp/.iir_sudo_pass | sudo -S usermod -aG docker $SSH_USER 2>/dev/null || true"

# ── SSH into server, build the image, restart only the IIR container ─────────
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash << ENDSSH
    set -e

    rm -f /tmp/.iir_sudo_pass

    TARGET_PATH="\$HOME/$TARGET_DIR"

    # 1. Clone the IIR branch into a build directory
    echo "📁 Preparing build environment at \$TARGET_PATH..."
    rm -rf "\$TARGET_PATH"
    mkdir -p "\$TARGET_PATH"
    cd "\$TARGET_PATH"

    echo "📥 Cloning repo (branch: $BRANCH)..."
    git clone --quiet -b "$BRANCH" "$GIT_AUTH_URL" .

    # 2. Build the IIR image (named so it cannot collide with scraper-tool-*)
    echo "🔨 Building Docker image: $IMAGE_NAME..."
    docker build -t "$IMAGE_NAME" .

    # 3. Strip source after build, leave only the compose file
    echo "🧹 Removing source code from server..."
    cd "\$HOME"
    rm -rf "\$TARGET_PATH"
    mkdir -p "\$TARGET_PATH"
    cd "\$TARGET_PATH"

    cp /tmp/iir-docker-compose.yml ./docker-compose.yml
    rm -f /tmp/iir-docker-compose.yml

    # 4. Stop ONLY the iir-scraper service in this compose project.
    #    Other compose projects on this host (staging-scraper, production-scraper,
    #    or any other team's containers) are unaffected.
    echo "🛑 Stopping existing IIR container (if any)..."
    docker-compose stop iir-scraper 2>/dev/null || true
    docker-compose rm -f iir-scraper 2>/dev/null || true

    # 5. Start the new container
    echo "🟢 Starting IIR container..."
    docker-compose up -d --no-build --remove-orphans

    # NOTE: deliberately NOT running 'docker image prune' here — that would
    # affect dangling images for other teams on this shared host.

    echo ""
    echo "✅ IIR deployment complete!"
    echo "   Frontend → http://$SSH_HOST:$FRONTEND_PORT"
    echo "   Backend  → http://$SSH_HOST:$BACKEND_PORT"
    echo "   API      → http://$SSH_HOST:$FRONTEND_PORT/api/scrapers/eiir?forename=&surname=&follow_details=true"
    echo ""
ENDSSH

echo "🏁 IIR deployment finished successfully!"
