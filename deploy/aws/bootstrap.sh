#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12-venv libgl1 libegl1 libglib2.0-0 curl gnupg unzip debian-keyring debian-archive-keyring apt-transport-https
cli_dir=$(mktemp -d /tmp/emotionlens-cli.XXXXXX)
curl --fail --silent --show-error --location --retry 3 https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o "$cli_dir/awscliv2.zip"
unzip -q "$cli_dir/awscliv2.zip" -d "$cli_dir"
"$cli_dir/aws/install" --update
rm -rf "$cli_dir"
curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
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
