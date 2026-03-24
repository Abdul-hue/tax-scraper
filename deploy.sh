#!/bin/bash

# ─────────────────────────────────────────────────────────────────────────────
# Scraper Tool — Deployment Script (Remote Build Strategy)
# Usage: ./deploy.sh [staging|production]
#
# Requires .env.deploy (in this dir, parent dir, or backend/) with:
#   SSH_HOST, SSH_USER, SSH_KEY_PATH, SSH_PASSWORD
#   GIT_USERNAME, GIT_PASSWORD, GIT_REPO_URL
# ─────────────────────────────────────────────────────────────────────────────

ENV=$1

if [[ "$ENV" != "staging" && "$ENV" != "production" ]]; then
    echo "Usage: ./deploy.sh [staging|production]"
    exit 1
fi

# Exit immediately on errors
set -e

# ── Load .env.deploy ─────────────────────────────────────────────────────────
DOTENV_DEPLOY=".env.deploy"
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "../.env.deploy" ]; then
    DOTENV_DEPLOY="../.env.deploy"
fi
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f ".emv.deploy" ]; then
    DOTENV_DEPLOY=".emv.deploy"
fi
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "../.emv.deploy" ]; then
    DOTENV_DEPLOY="../.emv.deploy"
fi
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "backend/.env.deploy" ]; then
    DOTENV_DEPLOY="backend/.env.deploy"
fi
if [ ! -f "$DOTENV_DEPLOY" ] && [ -f "backend/.emv.deploy" ]; then
    DOTENV_DEPLOY="backend/.emv.deploy"
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
    echo "❌ Error: Could not find .env.deploy or .emv.deploy in current, parent, or backend/ directory."
    exit 1
fi

# ── Validate required secrets ─────────────────────────────────────────────────
if [[ -z "$SSH_HOST" || -z "$SSH_USER" || -z "$SSH_KEY_PATH" || -z "$GIT_REPO_URL" || -z "$SSH_PASSWORD" ]]; then
    echo "❌ Error: Required secrets (SSH_HOST, SSH_USER, SSH_KEY_PATH, GIT_REPO_URL, SSH_PASSWORD) not found."
    exit 1
fi

# ── Environment Configuration ─────────────────────────────────────────────────
if [[ "$ENV" == "staging" ]]; then
    IMAGE_NAME="scraper-tool-staging"
    TARGET_DIR="staging-scraper"
    BRANCH="staging"
    FRONTEND_PORT=3412
    BACKEND_PORT=7887
else
    IMAGE_NAME="scraper-tool-production"
    TARGET_DIR="production-scraper"
    BRANCH="master"
    FRONTEND_PORT=3413
    BACKEND_PORT=7888
fi

GIT_AUTH_URL=$(echo "$GIT_REPO_URL" | sed "s|https://|https://${GIT_USERNAME}:${GIT_PASSWORD}@|")

echo ""
echo "🚀 Deploying [$ENV] to $SSH_USER@$SSH_HOST"
echo "   Branch        : $BRANCH"
echo "   Image         : $IMAGE_NAME"
echo "   Frontend Port : $FRONTEND_PORT"
echo "   Backend Port  : $BACKEND_PORT"
echo ""

# ── Sync docker-compose.yml to server ────────────────────────────────────────
DOCKER_COMPOSE="docker-compose.yml"
if [ ! -f "$DOCKER_COMPOSE" ] && [ -f "../docker-compose.yml" ]; then
    DOCKER_COMPOSE="../docker-compose.yml"
fi

echo "📤 Syncing docker-compose.yml to server..."
scp -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no \
    "$DOCKER_COMPOSE" "$SSH_USER@$SSH_HOST:/tmp/scraper-docker-compose.yml"

# ── Transfer password securely via a temp file ───────────────────────────────
PASS_TMPFILE=$(mktemp /tmp/scraper_deploy_pass.XXXXXX)
printf '%s' "$SSH_PASSWORD" > "$PASS_TMPFILE"
chmod 600 "$PASS_TMPFILE"
scp -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no \
    "$PASS_TMPFILE" "$SSH_USER@$SSH_HOST:/tmp/.scraper_sudo_pass"
rm -f "$PASS_TMPFILE"

# ── Add remote user to docker group (once) so no sudo needed for docker ──────
echo "🔧 Ensuring $SSH_USER is in docker group on remote server..."
ssh -tt -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" \
    "sudo -S usermod -aG docker $SSH_USER" < "$PASS_TMPFILE" 2>/dev/null || \
  ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" \
    "cat /tmp/.scraper_sudo_pass | sudo -S usermod -aG docker $SSH_USER 2>/dev/null || true"

# ── SSH into server (new session picks up docker group) ──────────────────────
ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" bash << ENDSSH
    set -e

    # Read sudo password (used only for docker-compose if needed)
    SUDO_PASS=\$(cat /tmp/.scraper_sudo_pass 2>/dev/null || echo "")
    rm -f /tmp/.scraper_sudo_pass

    TARGET_PATH="\$HOME/$TARGET_DIR"

    # ── 1. Clone the repo ────────────────────────────────────────────────────
    echo "📁 Preparing build environment at \$TARGET_PATH..."
    rm -rf "\$TARGET_PATH"
    mkdir -p "\$TARGET_PATH"
    cd "\$TARGET_PATH"

    echo "📥 Cloning repo (branch: $BRANCH)..."
    git clone --quiet -b "$BRANCH" "$GIT_AUTH_URL" .

    # ── 2. Build the Docker image ────────────────────────────────────────────
    echo "🔨 Building Docker image: $IMAGE_NAME..."
    docker build -t "$IMAGE_NAME" .

    # ── 3. Strip source code (security hygiene) ──────────────────────────────
    echo "🧹 Removing source code from server..."
    cd "\$HOME"
    rm -rf "\$TARGET_PATH"
    mkdir -p "\$TARGET_PATH"
    cd "\$TARGET_PATH"

    cp /tmp/scraper-docker-compose.yml ./docker-compose.yml
    rm -f /tmp/scraper-docker-compose.yml

    # ── 4. Stop old container ────────────────────────────────────────────────
    echo "🛑 Stopping existing containers..."
    export IMAGE_NAME="$IMAGE_NAME"
    export FRONTEND_PORT="$FRONTEND_PORT"
    export BACKEND_PORT="$BACKEND_PORT"
    docker-compose stop scraper 2>/dev/null || true
    docker-compose rm -f scraper 2>/dev/null || true

    # ── 5. Start the new container ───────────────────────────────────────────
    echo "🟢 Starting container..."
    docker-compose up -d --no-build --remove-orphans

    # ── 6. Prune old images ──────────────────────────────────────────────────
    echo "🗑️  Pruning stale images..."
    docker image prune -f

    echo ""
    echo "✅ Deployment complete!"
    echo "   Frontend → http://$SSH_HOST:$FRONTEND_PORT"
    echo "   Backend  → http://$SSH_HOST:$BACKEND_PORT"
    echo ""
ENDSSH

echo "🏁 [$ENV] deployment finished successfully!"
