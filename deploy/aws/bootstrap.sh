#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12-venv awscli libgl1 libegl1 libglib2.0-0 curl gnupg debian-keyring debian-archive-keyring apt-transport-https
curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
chmod a+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy
systemctl stop caddy
id emotionlens >/dev/null 2>&1 || useradd --system --home /var/lib/emotionlens --shell /usr/sbin/nologin emotionlens
install -d -m 755 /opt/emotionlens/releases
install -d -o emotionlens -g emotionlens -m 750 /var/lib/emotionlens
install -d -m 700 /etc/emotionlens
python3.12 -m venv /opt/emotionlens/venv
touch /opt/emotionlens/bootstrap-ready
