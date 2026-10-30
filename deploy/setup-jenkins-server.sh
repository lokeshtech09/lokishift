#!/usr/bin/env bash
# One-time setup for the CI server (Ubuntu 24.04, t3.large or bigger).
# Installs Jenkins + Docker + AWS CLI, and runs SonarQube in Docker.
#   run:  sudo bash setup-jenkins-server.sh
set -euo pipefail

echo "▶ Java 21 + Docker + tools"
apt-get update -y
apt-get install -y fontconfig openjdk-21-jre docker.io git curl unzip

echo "▶ AWS CLI v2"
if ! command -v aws >/dev/null; then
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscli.zip
    unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install
fi

echo "▶ Jenkins (LTS)"
wget -qO /usr/share/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" \
    > /etc/apt/sources.list.d/jenkins.list
apt-get update -y && apt-get install -y jenkins

echo "▶ Let Jenkins use Docker"
usermod -aG docker jenkins
systemctl enable --now docker
systemctl restart jenkins

echo "▶ SonarQube (Community) in Docker on port 9000"
# Elasticsearch inside SonarQube needs this kernel setting.
sysctl -w vm.max_map_count=524288
echo 'vm.max_map_count=524288' > /etc/sysctl.d/99-sonarqube.conf
docker volume create sonarqube_data >/dev/null
docker run -d --name sonarqube --restart unless-stopped \
    -p 9000:9000 -v sonarqube_data:/opt/sonarqube/data \
    sonarqube:community

echo
echo "✅ Done."
echo "   Jenkins   : http://<this-server-public-ip>:8080"
echo "   password  : $(cat /var/lib/jenkins/secrets/initialAdminPassword 2>/dev/null || echo 'sudo cat /var/lib/jenkins/secrets/initialAdminPassword')"
echo "   SonarQube : http://<this-server-public-ip>:9000   (admin / admin, change on first login)"
