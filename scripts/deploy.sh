#!/bin/bash
# Deploy LeadPeek to Hetzner VPS
# Usage: ./scripts/deploy.sh <server-ip> [ssh-key-path]

set -euo pipefail

SERVER_IP="${1:?Usage: ./scripts/deploy.sh <server-ip>}"
SSH_KEY="${2:-}"
SSH_OPTS="-o StrictHostKeyChecking=no"
[ -n "$SSH_KEY" ] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

echo "========================================="
echo "  LeadPeek Deploy to $SERVER_IP"
echo "========================================="

# Step 1: Install Docker on server (if needed)
echo ""
echo "[1/4] Installing Docker..."
ssh $SSH_OPTS root@$SERVER_IP << 'INSTALL_DOCKER'
if ! command -v docker &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    echo "Docker installed."
else
    echo "Docker already installed."
fi
INSTALL_DOCKER

# Step 2: Set up firewall
echo ""
echo "[2/4] Configuring firewall..."
ssh $SSH_OPTS root@$SERVER_IP << 'FIREWALL'
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "Firewall configured."
FIREWALL

# Step 3: Clone/update repo
echo ""
echo "[3/4] Deploying code..."
ssh $SSH_OPTS root@$SERVER_IP << 'DEPLOY_CODE'
cd /opt
if [ -d leadpeek ]; then
    cd leadpeek && git pull
else
    git clone https://github.com/albiezerozeroone-blip/leadpeek.git
    cd leadpeek
fi
DEPLOY_CODE

# Step 4: Build and start
#
# Note: /opt/leadpeek/.env.production is NOT uploaded from the laptop any more.
# It's canonical on the server — deploy.sh used to scp the laptop copy over it,
# which silently destroyed server-only secrets (e.g. OPENROUTER_API_KEY) when
# the laptop copy was out of sync. To change env vars, SSH to the server and
# edit /opt/leadpeek/.env.production directly. A dated backup is taken below
# so a bad edit can be rolled back within 30 days.
echo ""
echo "[4/4] Building and starting containers..."
ssh $SSH_OPTS root@$SERVER_IP << 'START'
cd /opt/leadpeek
# Guard deploys so we never kill a running NBB backload mid-hour.
# We wait for the shared lock and keep it held for the full deploy window.
STATE_DIR="/opt/leadpeek/scripts/_watchdog_state"
LOCK_FILE="$STATE_DIR/nbb_backload.lock"
LOCK_WAIT_SEC="${NBB_DEPLOY_LOCK_WAIT_SEC:-7200}"
mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
echo "Waiting (up to ${LOCK_WAIT_SEC}s) for NBB backload to finish..."
if ! flock -w "$LOCK_WAIT_SEC" 9; then
  echo "ERROR: timed out waiting for NBB backload lock ($LOCK_FILE)"
  echo "Aborting deploy to avoid interrupting a running backload."
  exit 1
fi
echo "NBB backload lock acquired; holding it during deploy."
# Dated backup of the env file — cheap insurance against fat-finger edits.
# Keeps one snapshot per deploy; prune with `rm .env.production.bak-*` if needed.
cp .env.production ".env.production.bak-$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null || true
docker compose down 2>/dev/null || true
# Free dangling images + build cache BEFORE the new build so we don't run
# the host out of disk. The shared Postgres on this host crashes on
# ENOSPC, taking down both prod and staging — learned the hard way.
DISK_USE=$(df / --output=pcent 2>/dev/null | tail -1 | tr -d ' %')
if [ "${DISK_USE:-0}" -gt 75 ]; then
  echo "Disk ${DISK_USE}% — pruning Docker artifacts..."
  docker image prune -af 2>/dev/null || true
  docker builder prune -af 2>/dev/null || true
  df -h / | tail -1
fi
docker compose up -d --build
echo ""
echo "Waiting for services to start..."
sleep 10
docker compose ps
START

echo ""
echo "========================================="
echo "  LeadPeek deployed!"
echo "  URL: http://$SERVER_IP"
echo "========================================="
