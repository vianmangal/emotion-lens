#!/bin/bash
# Run as root through SSM. Arguments contain artifact locations, never secrets.
set -euo pipefail
bucket=$1
release_id=$2
parameter=$3
region=${4:-ap-south-1}
[[ "$release_id" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
test -f /opt/emotionlens/bootstrap-ready
release=/opt/emotionlens/releases/$release_id
test ! -e "$release"
install -d -m 755 "$release"
aws s3 cp "s3://$bucket/releases/$release_id.tar.gz" /opt/emotionlens/release.tar.gz --region "$region" --only-show-errors
tar -xzf /opt/emotionlens/release.tar.gz -C "$release" --no-same-owner
rm /opt/emotionlens/release.tar.gz
ln -s /var/lib/emotionlens "$release/data"
/opt/emotionlens/venv/bin/pip install --no-cache-dir torch==2.5.1+cpu torchvision==0.20.1+cpu --index-url https://download.pytorch.org/whl/cpu
/opt/emotionlens/venv/bin/pip install --no-cache-dir -r "$release/backend/requirements-hosted.txt"
install -d -o emotionlens -g emotionlens -m 750 /var/lib/emotionlens/models
aws s3 cp "s3://$bucket/models/" /var/lib/emotionlens/models/ --recursive --region "$region" --only-show-errors
chown -R emotionlens:emotionlens /var/lib/emotionlens/models
aws ssm get-parameter --name "$parameter" --with-decryption --region "$region" --query Parameter.Value --output text > /etc/emotionlens/settings.json
chmod 600 /etc/emotionlens/settings.json
python3.12 - <<'PY'
import json
from pathlib import Path
config = json.loads(Path('/etc/emotionlens/settings.json').read_text())
config.pop('DEMO_AUTH_HASH', None)  # Ignore the retired owner-login setting.
# Values are JSON-quoted, which is valid systemd EnvironmentFile syntax.
Path('/etc/emotionlens/app.env').write_text(''.join(key + '=' + json.dumps(str(value)) + '\n' for key, value in config.items()))
PY
chmod 600 /etc/emotionlens/app.env
rm /etc/emotionlens/settings.json
ln -sfn "$release" /opt/emotionlens/current
install -m 644 "$release/deploy/aws/emotionlens.service" /etc/systemd/system/emotionlens.service
install -m 644 "$release/deploy/aws/Caddyfile" /etc/caddy/Caddyfile
rm -f /etc/systemd/system/caddy.service.d/emotionlens.conf
rm -f /etc/caddy/emotionlens-auth.env
systemctl daemon-reload
systemctl enable --now emotionlens
systemctl restart emotionlens
systemctl enable --now caddy
systemctl restart caddy
for attempt in $(seq 1 30); do
    if curl --fail --silent http://127.0.0.1:8000/health > /opt/emotionlens/health.json; then
        cat /opt/emotionlens/health.json
        exit 0
    fi
    sleep 2
done
exit 1
