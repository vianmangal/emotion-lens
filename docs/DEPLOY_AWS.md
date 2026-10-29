# AWS demo deployment (offline)

The owner requested a full shutdown on 2026-10-28, restoration on 2026-10-29, then another full shutdown on 2026-10-30. The replacement EC2 server was terminated and its EBS disk, Elastic IP, private S3 bucket and SSM runtime configuration were deleted. No active demo instances, disks, IP allocations, release buckets, configuration parameters, CloudFront distributions or demo log groups remained in the shutdown checks. No local demo server was listening. Phone calls are off, and the deleted Sarvam caller number was never replaced. Local project files and GitHub code remain available.

The following table records the final state after the 2026-10-30 shutdown (the original deployment was also removed on 2026-10-28):

| Resource | Verified shutdown state |
| --- | --- |
| EC2 demo server | Terminated |
| Root EBS disk | Deleted |
| Elastic public IP | Released |
| Private S3 release/backups bucket | All versions and bucket deleted |
| SSM runtime configuration | Deleted |
| Sarvam caller number | Permanently deleted; zero numbers, inbound deployments or outbound campaigns |
| Local calling | `SAFETY_CALL_MODE=off`, `SAFETY_DEMO_AUTO_CALLS=false`; caller number cleared |

GitHub Actions runs tests and builds only. Pushing source does not recreate infrastructure, rent a phone number or restart calling. The scripts below are retained for a future explicitly requested deployment; no host remains provisioned.

## Deployment architecture

The retired `cnn.vian1.tech` deployment used one Ubuntu 24.04 EC2 `c7i.xlarge` in `ap-south-1`, with an encrypted 20 GiB gp3 disk and a fixed public IPv4 address. Caddy served the production Vite build and terminated HTTPS, proxying the API and WebSocket to loopback port 8000. Only ports 80 and 443 were public; administration used AWS Systems Manager.

Releases live under `/opt/emotionlens/releases/`, selected by `/opt/emotionlens/current`. Models, SQLite and runtime data live separately under `/var/lib/emotionlens`. A private encrypted S3 bucket supplies releases; an SSM SecureString supplies runtime configuration as root-only systemd configuration. Both the original and replacement cloud resources have been removed.

Caddy rejects public `/safety/phone/*` and `/safety/events*` routes. Global manual call tests remain administration-only. Owner session status and cancellation use the session capability and `X-Safety-Owner` header. Never include credentials in browser bundles, URLs, archives or logs.

## Current optional demo behavior

Default sessions are live-only, with no saved incidents, clips or phone calls. Owner calling requires real mode, a configured provider/recipient and a private owner key. Explicit `SAFETY_DEMO_AUTO_CALLS=true` instead arms calling with Start camera and bypasses the owner-code form. Both calling modes are currently disabled. Enabled phone sessions save incident metadata without recording video.

Visual alerts retain 300 ms confirmation. A separate 1.5-second sustained-evidence timer starts a two-second cancelable call countdown. Stop, pause, tracking loss and disconnect cancel pending calls. Five-minute recipient cooldown, three-attempt hourly quota and no automatic retry of uncertain delivery still apply. Detector qualification remains false.

The native camera preview targets 30 FPS. Normal transport targets 20 FPS at 640×480/JPEG quality 75; optional demo transport targets 8 FPS at 384×288/quality 50. Four outstanding client frames overlap network latency. One active and one pending server frame bound work; cumulative acknowledgements prevent replaced frames from blocking uploads. Adjacent replacements within 500 ms preserve the RGB history. Action scoring requires at least 10 samples spanning three seconds with sufficient two-person coverage.

The clock adapter only lowers its initial HTTP clock estimate to the fastest observed WebSocket arrival; delayed frames cannot raise that estimate. Demo mode may rearm after transient timestamp/freshness pauses, but operator Stop and hidden-tab pauses require explicit resumption. Start camera can replace an abandoned demo session under the control lock, canceling its pending calls. Old-tab disconnects cannot stop its replacement. Recently observed boxes can remain visible for two seconds with a delayed-video label; hit freshness remains one second. Duplicate head/torso proposals are suppressed without imposing a two-person cap.

The hosted runner supports fixed-shape TorchScript CPU fusion with unchanged weights and FP32 precision. Historical isolated profiling on `c7i.xlarge` reduced warm feature inference from about 0.60 seconds to 0.40–0.42 seconds, with maximum feature difference `4.53e-6` and `allclose(atol=1e-5, rtol=1e-4)`. This measures numerical/performance behavior, not accuracy. Local execution remains eager by default. The v2 adapter separately bounds source computation age at two seconds and result publication age at one second; historical development accuracy reports are not new v2 webcam measurements.

## Checks and retained installation tools

```bash
python -m pytest
npm run test:unit --prefix deep_fe/frontend
npm run build --prefix deep_fe/frontend
npm run test:e2e --prefix deep_fe/frontend
```

`deploy/aws/bootstrap.sh` prepares a fresh host. `deploy/aws/install-release.sh BUCKET RELEASE_ID PARAMETER REGION` installs a uniquely named release through SSM, installs CPU Torch before hosted requirements, checks health and switches the current link. These tools require separately provisioned resources and do not run on GitHub push.

Any future release archive must exclude `.env`, credentials, virtual environments, Git metadata, databases, webcam images, logs, training footage and access notes. Visual model artifacts use the pinned hashes in `scripts/model_artifacts.json`.

For a future configured host, verify local `/health`, HTTPS, model loading, public phone-route rejection and WebSocket flow without placing a real call. Keep the prior release for rollback; switch the current link and service configuration without replacing runtime data. Back up SQLite with its online backup API before schema changes.

## Restoration verification (2026-10-29)

The frontend, valid HTTPS certificate, persistence and both detection models were checked on the replacement host. A prerecorded public development clip produced two tracked people and one possible-hit alert without a timestamp pause, including an injected 650 ms HTTP-arm delay. This is deployment regression evidence, not new webcam accuracy measurement. A public sample image also completed expression prediction. Global phone/event routes returned HTTP 403, and the server reported no configured phone provider or automatic calls.

The initial HTTPS certificate was issued with DNS validation because certificate-authority resolvers still cached the retired server address. It was imported into Caddy’s managed certificate storage; Caddy retained automatic certificate renewal until the server was terminated on 2026-10-30. The temporary Certbot renewal timer is disabled. The DNS validation TXT record remains in place and contains no private key.
