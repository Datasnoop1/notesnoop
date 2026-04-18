#!/bin/bash
# Deploy LeadPeek STAGING to Hetzner VPS on port 8080
# Usage: ./scripts/deploy_staging.sh <server-ip> [ssh-key-path]
#
# This runs alongside production. Staging uses:
#   - docker-compose.staging.yml (separate service names)
#   - nginx/staging.conf (HTTP only, no SSL)
#   - Port 8080 externally

set -euo pipefail

SERVER_IP="${1:?Usage: ./scripts/deploy_staging.sh <server-ip> [ssh-key-path]}"
SSH_KEY="${2:-}"
SSH_OPTS="-o StrictHostKeyChecking=no"
[ -n "$SSH_KEY" ] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

echo "========================================="
echo "  LeadPeek STAGING Deploy to $SERVER_IP"
echo "  Port: 8080"
echo "========================================="

# Step 1: Ensure Docker is installed
echo ""
echo "[1/4] Checking Docker..."
ssh $SSH_OPTS root@$SERVER_IP << 'CHECK_DOCKER'
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not installed. Run deploy.sh first."
    exit 1
fi
echo "Docker OK."
CHECK_DOCKER

# Step 2: Open port 8080
echo ""
echo "[2/4] Opening port 8080..."
ssh $SSH_OPTS root@$SERVER_IP << 'FIREWALL'
ufw allow 8080/tcp 2>/dev/null || true
echo "Port 8080 open."
FIREWALL

# Step 3: Sync code
echo ""
echo "[3/4] Deploying code..."
ssh $SSH_OPTS root@$SERVER_IP << 'DEPLOY_CODE'
cd /opt
if [ -d leadpeek ]; then
    cd leadpeek && git pull
else
    echo "ERROR: /opt/leadpeek not found. Run deploy.sh first."
    exit 1
fi
DEPLOY_CODE

# Step 4: Build and start staging containers
echo ""
echo "[4/4] Building and starting staging containers..."
ssh $SSH_OPTS root@$SERVER_IP << 'START'
cd /opt/leadpeek

# Stop existing staging containers (if any)
docker compose -f docker-compose.staging.yml -p leadpeek-staging down 2>/dev/null || true

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

# Build and start staging
docker compose -f docker-compose.staging.yml -p leadpeek-staging up -d --build

echo ""
echo "Waiting for services to start..."
sleep 10
docker compose -f docker-compose.staging.yml -p leadpeek-staging ps
START

echo ""
echo "========================================="
echo "  LeadPeek STAGING deployed!"
echo "  URL: http://$SERVER_IP:8080"
echo "========================================="
