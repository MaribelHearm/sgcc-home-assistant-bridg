# Implementation Plan: Add-on 接入官方 Chrome browser-service

## Steps
- [x] Map real state and affected paths.
- [x] Add app/browser image names to Docker Compose while keeping local build.
- [x] Install official Google Chrome and matching ChromeDriver in app image for Add-on embedded mode.
- [x] Keep sidecar browser image focused on official Chrome + browser manager.
- [x] Rework Add-on entrypoint to read `/data/options.json`, default to embedded `browser-service`, and keep Chrome on-demand.
- [x] Update ChromeDriver selection for `local` vs CDP/browser-service modes.
- [x] Harden sidecar entrypoint for Xvfb host-network conflicts and optional desktop helper exits.
- [x] Update CI to publish app/browser images to GHCR and ACR.
- [x] Update README, DOCS, Add-on tutorial, CHANGELOG, NOTICE, example.env, issue template.
- [x] Run static checks, unit tests, Docker builds, Add-on smoke, sidecar smoke, app→sidecar attach smoke.
- [x] Update ledger, handoff and quality gate.
- [ ] Commit, push `main`, tag/push `v0.1.3`, inspect CI.

## Paths
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/workflows/docker-image.yml`
- `CHANGELOG.md`
- `DOCS.md`
- `Dockerfile-for-github-action`
- `Dockerfile.browser`
- `NOTICE`
- `README.md`
- `config.yaml`
- `docker-compose.yml`
- `example.env`
- `ha_addons_doc/Add-on教程.md`
- `scripts/browser-service-entrypoint.sh`
- `scripts/browser.py`
- `scripts/docker-entrypoint.sh`
- `.workflow/`

## Validation commands
- `git diff --check`
- `bash -n scripts/docker-entrypoint.sh scripts/browser-service-entrypoint.sh`
- `python3 -m py_compile scripts/browser.py scripts/browser_service.py`
- `python3 - <<'PY' ... yaml.safe_load(...) ... PY`
- `PYTHONPATH=scripts python3 -m unittest scripts.test_mqtt_publisher -v`
- `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
- `docker build -f Dockerfile-for-github-action -t sgcc-app-addon-test .`
- `docker build -f Dockerfile.browser -t sgcc-browser-test .`
- `cp example.env .env && docker compose config >/tmp/sgcc-compose-config.yml && rm .env`
- Add-on embedded smoke with dummy `/app/main.py` and `/data/options.json`.
- Sidecar smoke: `/health` → `/start` → CDP `/json/version` → `/stop`.
- app→sidecar smoke: `build_driver()` attach official Chrome, read userAgent, `release_driver()` stops Chrome.

## Rollback points
- `git revert <commit>` for code/docs.
- Set `SGCC_BROWSER_MODE=local` for runtime rollback.
- Pin Compose/Add-on to previous image tag if release tag has problems.

## Do-not-touch
- Real SGCC account credentials.
- Real HA tokens / MQTT passwords.
- Unrelated repos or user directories.
