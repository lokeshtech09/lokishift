#!/usr/bin/env bash
# One-time setup for the app server (Ubuntu 24.04, t3.small is enough).
#   run:  sudo bash setup-app-server.sh
set -euo pipefail

apt-get update -y
apt-get install -y docker.io curl unzip

if ! command -v aws >/dev/null; then
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscli.zip
    unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install
fi

systemctl enable --now docker
usermod -aG docker ubuntu     # Jenkins deploys as this user over SSH

echo "✅ App server ready. Log out and back in once so 'ubuntu' can run docker."
