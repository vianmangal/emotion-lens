# AWS owner demo

Public hosting was separately requested on 2026-10-27. This supersedes the earlier PRD's local-only deployment scope; its earlier implementation/evaluation history remains preserved. The local runner still works without AWS.

## Deployment

- URL: `https://cnn.vian1.tech`, publicly accessible without a login.
- Region: `ap-south-1` (Mumbai), one Ubuntu 24.04 EC2 `c7i.xlarge` (4 vCPU, 8 GiB RAM) with encrypted 20 GiB gp3 storage and a fixed public IPv4 address. The initial `t3.medium` was too slow for the video sampling requirements. This instance runs person detection and background RGB inference concurrently; the v2 adapter handles bounded inference time separately from stale publications.
- Caddy serves the production Vite build and terminates HTTPS. `/safety/*`, `/predict` and `/health` proxy to FastAPI on loopback port 8000, including WebSockets.
- Only ports 80 and 443 are publicly reachable. Port 80 is for certificate validation and HTTPS redirects. Administration uses AWS Systems Manager; SSH and the raw API port are not exposed.
- Source releases live in `/opt/emotionlens/releases/`; `/opt/emotionlens/current` selects a release. SQLite, models and any runtime data live separately under `/var/lib/emotionlens` and survive code updates.
- The instance reads its release from a private, encrypted S3 bucket. Runtime configuration is an encrypted SSM SecureString at `/emotionlens/demo/config`, materialized as root-only systemd configuration. Provider secrets are never included in the frontend, source archive, Git or instance user data.
- Caddy rejects public `/safety/phone` routes with HTTP 403. Paid phone tests and their records remain accessible through server administration on the loopback API. The retired `DEMO_AUTH_HASH` configuration is ignored and no login environment file is installed.

This deployment is a single-camera personal demo, not a multi-user monitoring service. Webcam frames leave the visitor's machine for inference over TLS. Live-only sessions do not store video, incidents or schedule calls. Public visitors cannot access the manual call-test endpoint. Automatic real calls remain locked because detection qualification is unmet. No real call should be placed as a deployment health check.

CPU inference and network round-trip time affect tracking throughput and alert latency. The UI requests a 30 FPS native preview and targets 20 tracking updates/s, with at most two outstanding frames to overlap network round trips. The RGB model retains its trained 10 FPS history and approximately three-second window. These targets are not guaranteed cloud performance or accuracy.

The hosted runner enables fixed-shape TorchScript CPU inference fusion for the S3D feature extractor. Weights and FP32 precision remain unchanged. During initial profiling on `c7i.xlarge`, an isolated generated-input check reduced warm feature inference from about 0.60 seconds to 0.40–0.42 seconds, with maximum feature difference `4.53e-6` and `allclose(atol=1e-5, rtol=1e-4)`. This is numerical/performance verification, not action-accuracy validation. The normal local runner keeps its existing eager execution by default.

The v2 adapter separates result publication freshness (one second) from the source-window computation budget (two seconds), while retaining current body observations, dense history, session generation and transport freshness gates. This prevents normal bounded CPU inference time from repeatedly interrupting candidate confirmation and quiet-period clearing. Regression checks require a delayed positive episode to open and then clear, and separately reject stale sources and frozen publishers. Classification thresholds and weights are unchanged; the earlier v1 public-development report is historical, not a new v2 accuracy measurement.

## Build and update

`deploy/aws/bootstrap.sh` installs the base runtime on a fresh host. `deploy/aws/install-release.sh BUCKET RELEASE_ID PARAMETER REGION` installs a release through SSM. It requires a unique release directory, installs CPU Torch wheels before the pinned hosted requirements, verifies deployment health, and switches the `current` link. Keep dependency installation and service updates serialized on this single host.

The release archive contains application code, scripts, deployment configuration, the production frontend and the configured expression model. Visual backbone/person artifacts are uploaded separately with the pinned hashes from `scripts/model_artifacts.json`. Exclude `.env`, virtual environments, Git metadata, local databases, webcam images, logs, training videos and access notes.

```bash
python -m pytest
npm run test:unit --prefix deep_fe/frontend
npm run build --prefix deep_fe/frontend
npm run test:e2e --prefix deep_fe/frontend
```

After installation, check the localhost `/health` through SSM, then verify the public HTTPS certificate, frontend/API HTTP 200 responses without credentials, HTTP 403 for public phone routes, loaded model artifacts and WebSocket session flow. Check `systemctl status emotionlens caddy` and `journalctl -u emotionlens` through SSM for diagnosis. Logs must not contain provider keys or authorization headers.

## Rollback and persistence

Keep the previous release directory. Point `/opt/emotionlens/current` back to it, restore that release's service/Caddy configuration if changed, then restart the two services. Do not replace or delete `/var/lib/emotionlens` during a rollback. Back up SQLite with its online backup API before schema changes; copying a running WAL database file alone is insufficient.

Resources incur EC2, EBS, public IPv4 and small S3 charges while provisioned. Stopping the instance stops CPU billing but not disk or reserved-IP billing. Preserve runtime data and release references before intentionally removing resources. The older stopped EC2 record without a root volume is not used by this deployment.
