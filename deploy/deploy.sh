#!/usr/bin/env bash
# Runs ON the app EC2 instance (Jenkins copies it there over SSH).
#   usage: deploy.sh <registry> <image:tag> <aws-region>
# Pulls the new image from ECR, swaps the container, and fails the build
# if the new version doesn't answer its health check.
set -euo pipefail

REGISTRY="$1"
IMAGE="$2"
REGION="$3"
NAME=lokishift

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "▶ $IMAGE is already on this server (built by Jenkins here): no pull needed"
else
    echo "▶ Logging in to ECR"
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
    echo "▶ Pulling $IMAGE"
    docker pull "$IMAGE"
fi

PREVIOUS="$(docker inspect --format '{{.Config.Image}}' "$NAME" 2>/dev/null || true)"

echo "▶ Replacing container (data stays in the resume-data volume)"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
    -p 3000:3000 \
    -v resume-data:/app/backend/data \
    -e LOG_LEVEL=INFO \
    --restart unless-stopped \
    "$IMAGE"

echo "▶ Smoke test: /api/v1/health"
for i in $(seq 1 40); do
    if curl -fs http://127.0.0.1:3000/api/v1/health >/dev/null; then
        echo "✅ $IMAGE is healthy"
        docker image prune -f >/dev/null
        exit 0
    fi
    sleep 3
done

echo "❌ New version failed its health check"
docker logs --tail 50 "$NAME" || true
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$IMAGE" ]; then
    echo "↩ Rolling back to $PREVIOUS"
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" -p 3000:3000 -v resume-data:/app/backend/data \
        --restart unless-stopped "$PREVIOUS"
fi
exit 1
